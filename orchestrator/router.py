# INTENT PROMPT SHOULD MOVE TO GeneralQueryAgent if the user is trying to complete a verification
# of another document while one document is not yet complete

from typing import Tuple

from agent.kyc_agent import KYCManagerAgent
from agent.genral_query_agent import GeneralQueryAgent
from state import OverallState
from models.intent import OrchestratorDecision, UserIntent
from llm import LLMFactory 
from prompts.orchestrate import ORCHESTRATOR_PROMPT_TEMPLATE

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
        prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(
            active_workflow=state.get("active_workflow") or "None",
            kyc_step=state.get("kyc_step") or "None",
            response_to_user=state.get("ai_response", "None"),
            completed_workflows=state.get("completed_workflows", [])
        )
        
        try:
            # This uses the LLM's tool-calling feature to force a Pydantic response
            return self.llm_client._get_structured_response(
                human_prompt = user_message, 
                parser = OrchestratorDecision, 
                sys_prompt = prompt
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
        print("\n", "*"*35, "\n", decision.intent, "\n", "*"*35,)

        all_required_workflows = {"aadhaar", "pan"} # Define all possible workflows
        completed_workflows = set(state.get("completed_workflows", []))

# --------------------------------------------------------------------------------------------------------------
# This should be extended to other documents as well
# --------------------------------------------------------------------------------------------------------------
        if decision.intent in [UserIntent.START_AADHAAR_VERIFICATION, UserIntent.START_PAN_VERIFICATION]:
            workflow_to_start = 'aadhaar' if decision.intent == UserIntent.START_AADHAAR_VERIFICATION else 'pan'
            
            if workflow_to_start in completed_workflows:
                remaining_workflows = all_required_workflows - completed_workflows
                
                if not remaining_workflows: 
                    answer = "Your KYC verification is fully complete. We have already verified your Aadhaar and PAN. Thank you for your cooperation!"
                
                else:
                    next_workflow = remaining_workflows.pop()
                    answer = (f"We have already completed the {workflow_to_start} verification. "
                              f"Would you like to proceed with the {next_workflow.upper()} verification now?")
                
                state['active_workflow'] = None
                state["ai_response"] = answer
                
                return state, answer
        
        # if decision.intent in [UserIntent.START_AADHAAR_VERIFICATION, UserIntent.START_PAN_VERIFICATION]:
        #     workflow_to_start = 'aadhaar' if decision.intent == UserIntent.START_AADHAAR_VERIFICATION else 'pan'
        #     if workflow_to_start in state.get("completed_workflows", []):
        #         decision.intent = UserIntent.WORKFLOW_ALREADY_COMPLETE


        match decision.intent:
            case UserIntent.START_AADHAAR_VERIFICATION:
                state['active_workflow'] = 'aadhaar'
                updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                updated_state["ai_response"] = answer
                return updated_state, answer
                
            case UserIntent.START_PAN_VERIFICATION:
                state['active_workflow'] = 'pan'
                updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                updated_state["ai_response"] = answer
                return updated_state, answer

            case UserIntent.CONTINUE_ACTIVE_WORKFLOW | UserIntent.PROVIDE_CONFIRMATION_YES | UserIntent.PROVIDE_CONFIRMATION_NO:
                # For any continuation, we simply delegate to the KYC manager,
                # which will use the active_workflow already in the state.
                if not state.get("active_workflow"):
                    return state, "I'm sorry, I'm not sure which process you want to continue. Could you clarify?"
                
                updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                updated_state["ai_response"] = answer
                return updated_state, answer
            
            case UserIntent.PROVIDE_CONFIRMATION_NO:
                # If no workflow is active, the user is declining the suggestion to start the next one.
                if not state.get("active_workflow"):
                    answer = "Okay, no problem. Please let me know if you change your mind or if there's anything else I can help you with. Have a great day!"
                    updated_state["ai_response"] = answer
                    return state, answer

                # Otherwise, a workflow is active, and "no" is a response within that workflow.
                updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                updated_state["ai_response"] = answer
                return updated_state, answer
            
            case UserIntent.PROVIDE_CONFIRMATION_YES:
                if not state.get("active_workflow"):
                    all_workflows = {"aadhaar", "pan"}
                    completed = set(state.get("completed_workflows", []))
                    remaining = all_workflows - completed
                    if remaining:
                        next_workflow = remaining.pop()
                        updated_state['active_workflow'] = next_workflow
                        updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, "")
                        updated_state["ai_response"] = answer
                    else:
                        updated_state = state
                        answer = "Great! All KYC steps are complete. Is there anything else I can help with?"
                else:
                    # If a workflow is active, delegate the "yes" to the specialist.
                    updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                    updated_state["ai_response"] = answer

                return updated_state, answer
            
            case UserIntent.ASK_GENERAL_QUESTION:
                # Note: This call does not modify the KYC state.
                question = decision.argument or user_message
                _updated_state, answer = await self.general_query_agent.handle_step(state, question)
                
                # After answering, guide the user back to their pending task.
                guidance = self._get_guidance_message(state)
                return _updated_state, f"{answer}\n\n{guidance}"
            
            case UserIntent.FORCE_START_NEW_DOC_VERIFICATION:
                question = decision.argument or user_message
                answer = "We request you to first complete the verification of the current document, before starting the verification of another"
                return state, answer
            
            case UserIntent.WORKFLOW_ALREADY_COMPLETE:
                workflow = state.get('active_workflow', 'that document')
                answer = f"It looks like we have already successfully completed the {workflow} verification. Is there anything else you need help with?"
                state['active_workflow'] = None # Clear workflow as it's done
                return state, answer
            
            case UserIntent.POST_KYC_ACKNOWLEDGEMENT:
                answer = "Excellent. Your KYC verification is fully complete. Thank you for your cooperation! Is there anything else I can assist you with today?"
                return state, answer

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