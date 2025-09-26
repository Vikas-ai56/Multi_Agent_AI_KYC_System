# INTENT PROMPT SHOULD MOVE TO GeneralQueryAgent if the user is trying to complete a verification
# of another document while one document is not yet complete

from typing import Tuple, Literal

from agent.kyc_agent import KYCManagerAgent
from agent.genral_query_agent import GeneralQueryAgent
from agent.pan_check_agent import PanCheckAgent
from state import OverallState
from models.intent import OrchestratorDecision, UserIntent
from llm import LLMFactory 
from prompts.orchestrate import ORCHESTRATOR_PROMPT_TEMPLATE, FORM60_ROUTE_PROMPT
from memory.memory import MemoryManager

class MainOrchestrator:
    """
    The central routing agent for the entire system.
    It determines the user's high-level intent and delegates tasks to the appropriate manager agents.
    """
    def __init__(
        self,
        memory_client: MemoryManager
    ):

        self.llm_client = LLMFactory()
        self.kyc_manager = KYCManagerAgent()
        self.general_query_agent = GeneralQueryAgent()
        self.pan_check_agent = PanCheckAgent()
        self.fallback_message = (
            "I'm sorry, I didn't quite understand that. Could you please rephrase?"
            "Shall we continue the current process"
        )
        self.memory_manager = memory_client
        
    async def _get_intent(self, state: OverallState, user_message: str) -> OrchestratorDecision:
        """
        Uses a powerful, context-aware prompt with structured output (Pydantic)
        to reliably determine the user's intent.
        """      
        # memory_context = self.memory_manager.get_memory_context(user_message)
        memory_context = self.memory_manager.get_memory_context(
            query=user_message
        )
        
        # print("*"*25,"\n", memory_context,"\n","*"*25)

        prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(
            active_workflow=state.get("active_workflow") or "None",
            kyc_step=state.get("kyc_step") or "None",
            response_to_user=state.get("ai_response", "None"),
            completed_workflows=state.get("completed_workflows", []),
            memory_context = memory_context
        )
        
        try:
            return self.llm_client._get_structured_response(
                # model_id="gemini-2.5-pro",
                human_prompt = user_message, 
                parser = OrchestratorDecision, 
                sys_prompt = prompt
            )
        except Exception as e:
            print(f"Error during intent recognition: {e}")
            return OrchestratorDecision(intent=UserIntent.UNKNOWN, user_provides_data=False)

    async def _start_workflow(self, workflow_name: Literal["aadhaar", "pan", "form60"], state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        state['active_workflow'] = workflow_name
        message_for_agent = "" if state.get("kyc_step") is None else user_message
        
        updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, message_for_agent)
        updated_state["ai_response"] = answer
        return updated_state, answer

    async def route(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        """
        The main entry point for the orchestrator.
        1. Gets the structured intent from the LLM.
        2. Routes to the appropriate manager based on the intent.
        3. Returns the updated state and the response to the user.
        """
        state['input_message'] = user_message
        decision = await self._get_intent(state, user_message)
        current_kyc_step = state.get("kyc_step")

        print("\n", "*"*35, "\n", decision.intent, "\n", "*"*35,)

        if current_kyc_step == "awaiting_pan_probe_response":
            final_state, response_message = await self.pan_check_agent.handle_step(state, user_message)
            final_state["ai_response"] = response_message
            return final_state, response_message
        
        if current_kyc_step == "awaiting_final_pan_decision":
            final_state, response_message = await self._start_workflow("pan" if "yes" in user_message.lower() else "form60", state, user_message)
            return final_state, response_message
        
        all_required_workflows = {"aadhaar", "pan", "passport", "dl"} 
        completed_workflows = set(state.get("completed_workflows", []))
        print("\n", "*"*35, "\n", state.get("active_workflow"), "\n", "*"*35,)
        print("\n", "*"*35, "\n", completed_workflows, "\n", "*"*35,)
        
# --------------------------------------------------------------------------------------------------------------
# This should be extended to other documents as well
# --------------------------------------------------------------------------------------------------------------
        if decision.intent in [UserIntent.START_AADHAAR_VERIFICATION, UserIntent.START_PAN_VERIFICATION, UserIntent.START_DL_VERIFICATION, UserIntent.START_PASSPORT_VERIFICATION]:
            workflow_to_start = 'aadhaar' if decision.intent == UserIntent.START_AADHAAR_VERIFICATION else 'pan'
            
            if workflow_to_start in completed_workflows:
                remaining_workflows = all_required_workflows - completed_workflows
                
                if not remaining_workflows: 
                    answer = "Your KYC verification is fully complete. We have already verified your documents. Thank you for your cooperation!"
                
                else:
                    next_workflow = remaining_workflows.pop()
                    answer = (f"We have already completed the verification of this document.\n"
                              f"Would you like to proceed with the {next_workflow.upper()} verification now?")
                
                state['active_workflow'] = None
                state["ai_response"] = answer
                
                final_state, response_message = state, answer
        
        match decision.intent:
            case UserIntent.START_AADHAAR_VERIFICATION:
                state['active_workflow'] = 'aadhaar'
                final_state, response_message = await self.kyc_manager.delegate_to_specialist(state, user_message)
                final_state["ai_response"] = response_message
                
            case UserIntent.START_PAN_VERIFICATION:
                state['active_workflow'] = 'pan'
                final_state, response_message = await self.kyc_manager.delegate_to_specialist(state, user_message)
                final_state["ai_response"] = response_message

            case UserIntent.START_PASSPORT_VERIFICATION:
                state['active_workflow'] = 'passport'
                final_state, response_message = await self.kyc_manager.delegate_to_specialist(state, user_message)
                final_state["ai_response"] = response_message
            
            case UserIntent.START_DL_VERIFICATION:
                state['active_workflow'] = 'dl'
                final_state, response_message = await self.kyc_manager.delegate_to_specialist(state, user_message)
                final_state["ai_response"] = response_message

            case UserIntent.START_FORM60_VERIFICATION:
                if "pan" in completed_workflows:
                    response_message = "You have completed this verification step. You need not do it again."
                
                state["active_workflow"] = "form60"
                return await self._start_workflow("form60", state, user_message)

            case UserIntent.CONTINUE_ACTIVE_WORKFLOW:
                if not state.get("active_workflow"):
                    return state, "I'm sorry, I'm not sure which process you want to continue. Could you clarify?"
                
                final_state, response_message = await self.kyc_manager.delegate_to_specialist(state, user_message)
                final_state["ai_response"] = response_message
            
            case UserIntent.PROVIDE_CONFIRMATION_NO:
                # If no workflow is active, the user is declining the suggestion to start the next one.
                if not state.get("active_workflow"):
                    answer = "Okay, no problem. Please let me know if you change your mind or if there's anything else I can help you with. Have a great day!"
                    updated_state = state
                    updated_state["ai_response"] = answer
                    return updated_state, answer

                # Otherwise, a workflow is active, and "no" is a response within that workflow.
                updated_state, answer = await self.kyc_manager.delegate_to_specialist(state, user_message)
                updated_state["ai_response"] = answer
                return updated_state, answer
            
            case UserIntent.PROVIDE_CONFIRMATION_YES:
                if not state.get("active_workflow"):
                    all_workflows = {"aadhaar", "pan", "passport", "dl"}
                    completed = set(state.get("completed_workflows", []))
                    remaining = all_workflows - completed
                    if remaining:
                        next_workflow = remaining.pop(0)
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
                if not state["kyc_step"]: 
                    answer = f"It looks like we have already successfully completed the verification of this document. Is there anything else you need help with?"
                else:
                    guidance = self._get_guidance_message(state)
                    answer = f"It looks like we have already successfully completed the verification of this document. {guidance}"

                state['active_workflow'] = None # Clear workflow as it's done
                return state, answer
            
            case UserIntent.POST_KYC_ACKNOWLEDGEMENT:
                answer = "Excellent. Your KYC verification is fully complete. Thank you for your cooperation! Is there anything else I can assist you with today?"
                return state, answer
            
            case UserIntent.DECLARE_NO_PAN:
                if not state.get("pan_probe_complete"):
                    # Start the PAN check probe workflow
                    state["active_workflow"] = "pan_check"
                    updated_state, answer = await self.pan_check_agent.handle_step(state, user_message)
                    updated_state["ai_response"] = answer
                    return updated_state, answer
                else:
                    return await self._start_workflow("form60", state, user_message)

            case UserIntent.PROCEED_WITH_FORM60:
                final_state = state
                if state.get("active_workflow"):
                    response_message = f"I understand. But you are not authorized to initiate the Form 60 verification process.\nPlease proceed with the {state.get('active_workflow')} verification process."
                else:
                    response_message = "I understand. But you are not authorized to initiate the Form 60 verification process."

            case _: # Handles UNKNOWN
                if state.get("active_workflow") == None:
                    remaining_doc = list(all_required_workflows - completed_workflows)

                    if remaining_doc:
                        next_doc = remaining_doc[-1]
                        fallback_message = ("I'm sorry, I didn't quite understand that. Could you please rephrase?"
                                            f"Shall we start the verification of {next_doc}. If you have it available with you")
                        response_message = fallback_message  # ← Only set here
                        final_state = state
        
                    else:
                        fallback_message = ("I'm sorry, I didn't quite understand that. Could you please rephrase?"
                                            f"You have completed your KYC, You can press EXIT to end the process.")
                        return state, fallback_message
                        
                else:
                    guidance = self._get_guidance_message(state)
                    fallback_message = "I'm sorry, I didn't quite understand that. Could you please rephrase?" + guidance
                    
                    response_message = fallback_message  # ← Only set here
                    final_state = state
                    
        self.memory_manager.add_turn(user_message, response_message, state["active_workflow"])
        return final_state, response_message
    
    async def _handle_pan_probe_response(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        system_prompt = FORM60_ROUTE_PROMPT.format(question=state["ai_response"], user_message=user_message)
        message = self.llm_client._get_normal_response(human_prompt=user_message, sys_prompt=system_prompt)
        
        if "yes" in message.lower():
            state["kyc_step"] = "awaiting_final_pan_decision"
            answer = "Based on that information, it's likely a PAN card would have been required. Verification is mandatory if you have one. Would you like to try the PAN verification process now (Yes/No)?"
            state["ai_response"] = answer
            return state, answer
        else:
            return await self._start_workflow("form60", state, user_message)
        
    def _get_guidance_message(self, state: OverallState) -> str:
        """Generates a helpful message to guide the user back to a pending workflow."""
        kyc_step = state.get("kyc_step")
        if kyc_step == "awaiting_aadhaar_input":
            return "Now, returning to your Aadhaar verification, could you please provide the 12-digit number?"
        if kyc_step == "awaiting_pan_confirmation":
            return "Now, regarding the PAN details shown above, was the information correct (Yes/No)?"
        if kyc_step == "awaiting_bank_account_response":
            return "Please answer: Do you have a bank account?"
        if kyc_step == "awaiting_itr_response":
            return "Please answer: Have you filed an Income Tax Return (ITR) in India in the last 3 years?"
        if kyc_step == "awaiting_occupation_response":
            return "Please answer: What best describes your occupation?"
        if kyc_step == "awaiting_double_confirmation_pan":
            return "⚠️ Please confirm: Do you have a PAN card and wish to proceed with PAN verification? (Yes/No)"
        if kyc_step == "awaiting_double_confirmation_form60":
            return "⚠️ Please confirm: Do you not have a PAN card and wish to proceed with Form 60? (Yes/No)"
        if state.get("active_workflow"):
            return f"Whenever you're ready, we can continue with the {state['active_workflow']} verification."
        return "Let me know how I can help you further!"