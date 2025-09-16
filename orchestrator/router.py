from typing import Tuple

from agent.kyc_agent import KYCManagerAgent
from agent.genral_query_agent import GeneralQueryAgent
from state import OverallState
from models.intent import OrchestratorDecision, UserIntent
from llm import LLMFactory 

class MainOrchestrator:
    """
    The central routing agent for the entire system.
    It determines the user's high-level intent and delegates tasks to the appropriate manager agents.
    """
    def __init__(self):
        self.llm_client = LLMFactory()
        self.kyc_manager = KYCManagerAgent()
        self.general_query_agent = GeneralQueryAgent()
        self.fallback_message = "I'm sorry, I didn't quite understand that. Could you please rephrase?"

    async def _get_intent(self, state: OverallState, user_message: str) -> OrchestratorDecision:
        """
        Uses a powerful, context-aware prompt with structured output (Pydantic)
        to reliably determine the user's intent.
        """
        
        system_prompt_template = """
        You are the central routing agent for an advanced, conversational insurance KYC system.
        Your primary role is to analyze the user's message and the current conversation state to determine the user's high-level intent.
        You MUST format your output as the 'OrchestratorDecision' tool.

        **Current Conversation State:**
        - Active Workflow: {active_workflow} 
        - Current KYC Step: {kyc_step} 

        **Your Decision Logic (Follow these rules in order):**
        1.  **PRIORITY 1: Continue Active Workflow.** If 'Active Workflow' is NOT 'None', the user is in the middle of a process. 
            - If the user provides data (a number, name, date, 'yes'/'no'), their intent is ALWAYS 'CONTINUE_ACTIVE_WORKFLOW'.
            - The ONLY exception is if they explicitly ask a question starting with 'what is', 'explain', 'can you tell me', etc. In that case, see rule 2.

        2.  **PRIORITY 2: Answer General Questions.** If the user asks a general question about insurance concepts (e.g., "What is a premium?", "Explain term life insurance"), their intent is 'ASK_GENERAL_QUESTION'. You must extract the specific question into the 'argument' field. This applies even if a workflow is active.

        3.  **PRIORITY 3: Start a New Workflow.** If 'Active Workflow' is 'None', analyze the user message to identify if they want to start a new verification process.
            - "verify my aadhaar", "start with aadhaar" -> 'START_AADHAAR_VERIFICATION'
            - "check my PAN card", "i have a PAN" -> 'START_PAN_VERIFICATION'

        4.  **Fallback.** If none of the above rules match, the intent is 'UNKNOWN'.
        """
        
        prompt = system_prompt_template.format(
            active_workflow=state.get("active_workflow") or "None",
            kyc_step=state.get("kyc_step") or "None"
        )
        
        try:
            # This uses the LLM's tool-calling feature to force a Pydantic response
            return self.llm_client._get_structured_response(
                user_message, 
                OrchestratorDecision, 
                sys_prompt=prompt
            )
        except Exception as e:
            print(f"Error during intent recognition: {e}")
            return OrchestratorDecision(intent=UserIntent.UNKNOWN, user_provides_data=False)


    async def route(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        """
        The main entry point for the orchestrator.
        1. Gets the structured intent from the LLM.
        2. Routes to the appropriate manager based on the intent.
        3. Returns the updated state and the response to the user.
        """
        state['input_message'] = user_message
        decision = await self._get_intent(state, user_message)

        match decision.intent:
            case UserIntent.START_AADHAAR_VERIFICATION:
                state['active_workflow'] = 'aadhaar'
                return await self.kyc_manager.delegate_to_specialist(state, user_message)

            case UserIntent.START_PAN_VERIFICATION:
                state['active_workflow'] = 'pan'
                return await self.kyc_manager.delegate_to_specialist(state, user_message)

            case UserIntent.CONTINUE_ACTIVE_WORKFLOW | UserIntent.PROVIDE_CONFIRMATION_YES | UserIntent.PROVIDE_CONFIRMATION_NO:
                # For any continuation, we simply delegate to the KYC manager,
                # which will use the active_workflow already in the state.
                if not state.get("active_workflow"):
                    return state, "I'm sorry, I'm not sure which process you want to continue. Could you clarify?"
                return await self.kyc_manager.delegate_to_specialist(state, user_message)

            case UserIntent.ASK_GENERAL_QUESTION:
                # Note: This call does not modify the KYC state.
                question = decision.argument or user_message
                _updated_state, answer = await self.general_query_agent.handle_step(state, question)
                
                # After answering, guide the user back to their pending task.
                guidance = self._get_guidance_message(state)
                return state, f"{answer}\n\n{guidance}"

            case _: # Handles UNKNOWN
                return state, self.fallback_message
    
    def _get_guidance_message(self, state: OverallState) -> str:
        """Generates a helpful message to guide the user back to a pending workflow."""
        kyc_step = state.get("kyc_step")
        if kyc_step == "awaiting_aadhaar_input":
            return "Now, returning to your Aadhaar verification, could you please provide the 12-digit number?"
        if kyc_step == "awaiting_pan_confirmation":
            return "Now, regarding the PAN details shown above, was the information correct (Yes/No)?"
        if state.get("active_workflow"):
            return f"Whenever you're ready, we can continue with the {state['active_workflow']} verification."
        return "Let me know how I can help you further!"