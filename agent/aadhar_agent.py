import datetime
from typing import Tuple, Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver # Use a persistent checkpointer in production
from langgraph.types import Command

# Assuming these are in the correct paths
from agent.base_agent import BaseSpecialistAgent
from tools import aadhar_tools
from state import OverallState, AadharGraphState, AadharDetailsState, VerificationState
from llm import LLMFactory

class AadharAgent(BaseSpecialistAgent):
    """
    An expert agent for Aadhaar verification, implemented as a robust, interruptible LangGraph state machine.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        
        builder = StateGraph(AadharGraphState)

        # --- Node Definitions ---
        builder.add_node("prompt_for_aadhaar", self._prompt_for_aadhaar)
        builder.add_node("validate_and_verify", self._validate_and_verify)
        builder.add_node("handle_invalid_format", self._handle_invalid_format)
        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)
        builder.add_node("finish_aadhaar_process", self._finish_aadhaar_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)
        # <<< CHANGE >>> Added a new node to handle data mismatch, improving clarity.
        builder.add_node("handle_data_mismatch", self._handle_data_mismatch)


        # --- Edge Definitions ---
        builder.add_edge(START, "prompt_for_aadhaar")
        # After prompting, the graph will pause. On resume, it will validate.
        builder.add_edge("prompt_for_aadhaar", "validate_and_verify")

        builder.add_conditional_edges(
            "validate_and_verify",
            lambda s: s.get("decision"),
            {"proceed": "prompt_for_confirmation", "retry": "handle_invalid_format"}
        )
        
        builder.add_conditional_edges(
            "handle_invalid_format",
            lambda s: s.get("decision"),
            {"retry": "prompt_for_aadhaar", "terminate": "terminate_workflow"}
        )
        
        # <<< CHANGE >>> After confirmation, the user can agree or disagree (mismatch).
        builder.add_conditional_edges(
            "prompt_for_confirmation",
            self._decide_after_confirmation,
            {"proceed": "finish_aadhaar_process", "mismatch": "handle_data_mismatch"}
        )

        builder.add_edge("finish_aadhaar_process", END)
        builder.add_edge("terminate_workflow", END)
        builder.add_edge("handle_data_mismatch", END) 
        
        # --- Graph Compilation with CORRECT Interruption Pattern ---
        checkpointer = InMemorySaver()
        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after=["prompt_for_aadhaar", "prompt_for_confirmation"]
        )

    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        graph_input: AadharGraphState = {
            "session_id": state["session_id"],
            "user_message": user_message,
            "retries": state.get("aadhaar_retries", 0),
        }
        
        config = {"configurable": {"thread_id": state["session_id"]}}
        final_graph_state = None

        while True:
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
                break
            except Command:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values[-1]
                break

        state["aadhaar_retries"] = final_graph_state["retries"]
        
        checkpoint = list(self.graph.get_state(config))
        last_node = checkpoint[-2].next[0]
        
        # Check if the graph is paused waiting for input.
        if checkpoint and checkpoint.next:
            if last_node == "prompt_for_aadhaar":
                state["kyc_step"] = "awaiting_aadhaar_input"
            elif last_node == "prompt_for_confirmation":
                state["kyc_step"] = "awaiting_aadhaar_confirmation"
        else:
            # The workflow has truly finished (hit an END node).
            state["kyc_step"] = None
            if last_node == "finish_aadhaar_process":
                verified_data = final_graph_state["verified_data"]
                state["aadhar_details"] = AadharDetailsState(
                    aadhar_number=verified_data["aadhar_number"],
                    name=verified_data["name"],
                    date_of_birth=verified_data["date_of_birth"],
                    new_doc_needed=False
                )
                state["aadhar_verification_status"] = VerificationState(
                    verification_status="success",
                    verification_message="Aadhaar details successfully verified from database.",
                    verification_timestamp=datetime.datetime.now().isoformat(),
                    verification_doc="Aadhaar e-Verification"
                )
                if "aadhaar" not in state.get("completed_workflows", []):
                    state["completed_workflows"] = state.get("completed_workflows", []) + ["aadhaar"]
        
        return state, final_graph_state["response_to_user"]

    # --- Graph Node Methods (Private) ---
    def _prompt_for_aadhaar(self, state: AadharGraphState) -> AadharGraphState:
        # <<< CHANGE >>> Simplified the prompt logic for clarity and consistency.
        base_prompt = (
            "To begin your secure Aadhaar verification, please enter your 12-digit Aadhaar number. "
            "Your information is encrypted and used only for this E-KYC process."
        )
        retry_prompt = (
            "It seems that number was not found or was invalid. "
            "Please carefully re-enter your 12-digit Aadhaar number."
        )
        
        message = retry_prompt if state.get("retries", 0) > 0 else base_prompt
        # The LLM call could be used here to stylize the message, as in your original code.
        # For example: self.llm_client._get_normal_response(message, sys_prompt=SYSTEM_PROMPT)
        
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_aadhaar"
        }

    def _validate_and_verify(self, state: AadharGraphState) -> AadharGraphState:
        aadhaar_number = state["user_message"].strip()
        if not aadhar_tools.validate_aadhaar_format(aadhaar_number):
            return {"decision": "retry"}

        result = aadhar_tools.verify_aadhaar_in_database(aadhaar_number)
        if result.status == "success":
            return {"decision": "proceed", "verified_data": result.verified_data.model_dump()}
        else:
            return {"decision": "retry"}

    def _handle_invalid_format(self, state: AadharGraphState) -> AadharGraphState:
        retries = state.get("retries", 0) + 1
        return {"retries": retries, "decision": "terminate" if retries >= 2 else "retry"}

    def _prompt_for_confirmation(self, state: AadharGraphState) -> AadharGraphState:
        verified_data = state["verified_data"]
        message = (
            "Excellent! We've successfully verified your Aadhaar. Here are the details we found:\n\n"
            f"- **Name:** {verified_data['name']}\n"
            f"- **Date of Birth:** {verified_data['date_of_birth']}\n\n"
            "Is this information correct (Yes/No)?"
        )
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }

    # <<< CHANGE >>> The decision now routes to a dedicated "mismatch" node.
    def _decide_after_confirmation(self, state: AadharGraphState) -> Literal["proceed", "mismatch"]:
        return "proceed" if "yes" in state["user_message"].lower() else "mismatch"
    
    # <<< CHANGE >>> Added this new node to handle the "No" case from the user.
    def _handle_data_mismatch(self, state: AadharGraphState) -> AadharGraphState:
        message = (
            "I understand. Since the details retrieved from the official Aadhaar database are not correct, "
            "we cannot proceed with the automated process. We advise you to get your Aadhaar details corrected. "
            "For now, we will have to terminate this verification."
        )
        return {"response_to_user": message}

    def _finish_aadhaar_process(self, state: AadharGraphState) -> AadharGraphState:
        message = "Thank you. Your Aadhaar details have been successfully confirmed."
        next_steps_suggestion = self._suggest_next_steps(state)
        return {
            "response_to_user": message + " " + next_steps_suggestion,
            "verified_data": state["verified_data"], # Pass data through
            "status": "SUCCESS"
        }

    def _terminate_workflow(self, state: AadharGraphState) -> AadharGraphState:
        message = "I'm sorry, we couldn't verify your Aadhaar details after multiple attempts. Please contact support for assistance."
        return {"response_to_user": message}

    def _suggest_next_steps(self, state: OverallState) -> str:
        completed: Set[str] = set(state.get("completed_workflows", []))
        # This check is now done in handle_step, but we keep it here for robustness
        if "aadhaar" not in completed:
             completed.add("aadhaar")
        remaining_docs = self.all_workflows - completed
        if not remaining_docs:
            return "You have now completed all required document verifications!"
        else:
            next_doc = list(remaining_docs)[0].capitalize()
            return f"Would you like to proceed with your {next_doc} verification now?"