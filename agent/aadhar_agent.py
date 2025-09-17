# THE SUGGEST NEXT STEP IS HANDLED IN SUCH A WAY EITHER BOTH PAN AND FORM60 
# are there in `remaining_docs` or both are not

import datetime
from typing import Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver # Use a persistent checkpointer in production
from langgraph.types import Command, Interrupt
from langsmith import traceable

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
        builder.add_node("validate_aadhaar_format", self._validate_aadhaar_format)
        builder.add_node("handle_invalid_format_aa_no", self._handle_invalid_format_aa_no)

        builder.add_node("prompt_for_otp", self._prompt_for_otp)
        builder.add_node("validate_otp_format", self._validate_otp_format)
        builder.add_node("handle_invalid_otp_format", self._handle_invalid_otp_format)
        
        builder.add_node("validate_otp_correctness", self._validate_otp_correctness)
        builder.add_node("verify_from_uidai", self._verify_from_uidai)
        builder.add_node("handle_db_failure", self._handle_db_failure)

        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)
        builder.add_node("finish_aadhaar_process", self._finish_aadhaar_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)
        builder.add_node("handle_data_mismatch", self._handle_data_mismatch)


        # --- Edge Definitions ---
        builder.add_edge(START, "prompt_for_aadhaar")
        builder.add_edge("prompt_for_aadhaar", "validate_aadhaar_format")

        builder.add_conditional_edges(
            "validate_aadhaar_format",
            lambda s: s.get("decision"),
            {"valid": "prompt_for_otp", "invalid": "handle_invalid_format_aa_no"}
        )

        builder.add_conditional_edges(
            "handle_invalid_format_aa_no",
            lambda s: s.get("decision"),
            {"retry": "prompt_for_aadhaar", "terminate": "terminate_workflow"}
        )

        builder.add_edge("prompt_for_otp", "validate_otp_format")

        builder.add_conditional_edges(
            "validate_otp_format",
            lambda s: s.get("decision"),
            {"valid": "validate_otp_correctness", "invalid": "handle_invalid_otp_format"}
        )

        builder.add_conditional_edges(
            "handle_invalid_otp_format",
            lambda s: s.get("decision"),
            {"retry": "prompt_for_otp", "terminate": "terminate_workflow"}
        )

        builder.add_conditional_edges(
            "validate_otp_correctness",
            lambda s: s.get("decision"),
            {
                "proceed": "verify_from_uidai",      # If correct, verify against DB
                "retry": "prompt_for_otp",           # If incorrect, ask for OTP again
                "terminate": "terminate_workflow"    # If too many OTP retries, terminate
            }
        )

        builder.add_conditional_edges(
            "verify_from_uidai",
            lambda s: s.get("decision"),
            {
                "proceed": "prompt_for_confirmation", # If DB lookup succeeds, ask for confirmation
                "db_failure": "handle_db_failure"     # If DB lookup fails, handle that specific failure
            }
        )
        
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
            interrupt_after=["prompt_for_aadhaar", "prompt_for_confirmation", "prompt_for_otp"]
        )

    @traceable(name="AADHAAR_AGENT_HANDLE_STEP")
    async def handle_step(self, state, user_message):
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None

        if checkpoint and checkpoint.next:
            try:
                if user_message:
                    await self.graph.aupdate_state(config=config, values={"user_message":user_message})
                    final_graph_state = await self.graph.ainvoke(Command(resume=user_message), config=config)
                else:
                    final_graph_state = await self.graph.ainvoke(None, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        else:
            graph_input = {
                "session_id": state["session_id"],
                "user_message": user_message,
                "retries": state.get("aadhar_retries", 0),
                "decision": None,
                "otp_retries": state.get("otp_retries", 0),
                "verified_data": state.get("verified_data",{}),
                "last_executed_node": state.get("last_executed_node",""),
                "status":"IN_PROGRESS"
            }

            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values
            
        state["verified_data"] = final_graph_state.get("verified_data", {})
        state["aadhar_retries"] = final_graph_state.get("retries", 0)
        state["otp_retries"] = final_graph_state.get("otp_retries", 0)

        last_node = final_graph_state.get("last_executed_node")

        if last_node == "prompt_for_aadhaar":
            state["kyc_step"] = "awaiting_aadhaar_input"

        elif last_node == "prompt_for_otp":
            state["kyc_step"] = "awaiting_otp_input"

        elif last_node == "prompt_for_confirmation":
            state["kyc_step"] = "awaiting_aadhaar_confirmation"

        if final_graph_state.get("status") in ["SUCCESS", "FAILURE"]:
            # Mark the workflow as "completed" so the orchestrator doesn't ask again.
            if "aadhaar" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["aadhaar"]
            
            state["active_workflow"] = None
            state["kyc_step"] = None

            # If it was a success, update state and suggest next steps
            if final_graph_state.get("status") == "SUCCESS":
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
                next_step = self._suggest_next_steps(state)
                final_graph_state["response_to_user"] += "\n" + next_step

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    @traceable
    def _prompt_for_aadhaar(self, state: AadharGraphState) -> AadharGraphState:
        base_prompt = (
            "To begin your secure Aadhaar verification, please enter your 12-digit Aadhaar number. "
            "Your information is encrypted and used only for this E-KYC process."
        )
        retry_prompt = (
            "It seems that number was not found or was invalid. "
            "Please carefully re-enter your 12-digit Aadhaar number."
        )
        
        message = retry_prompt if state.get("retries", 0) > 0 else base_prompt
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_aadhaar"
        }
    
    @traceable
    def _prompt_for_otp(self, state: AadharGraphState) -> AadharGraphState:
        base_prompt = (
            "Please enter the 6-digit OTP sent to your the mobile number which is linked your aadhaar card."
        )
        retry_prompt = (
            "It seems that OTP was found invalid. "
            "Please carefully re-enter your 6-digit OTP."
        )

        message = retry_prompt if state.get("otp_retries", 0) > 0 else base_prompt
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_otp"
        }
    
    @traceable
    def _validate_aadhaar_format(self, state: AadharGraphState) -> AadharGraphState:
        """Checks if the provided Aadhaar number has a valid format (12 digits)."""
        aadhaar_number = state["user_message"].strip()
        if aadhar_tools.validate_aadhaar_format(aadhaar_number):
            return {"decision": "valid", "verified_data": {"aadhar_number": aadhaar_number}}
        else:
            return {"decision": "invalid"}

    @traceable
    def _validate_otp_correctness(self, state: AadharGraphState) -> AadharGraphState:
        """Validates if the provided OTP is the correct one."""
        user_otp = state["user_message"].strip()
        
        # Spoofed OTP check
        if user_otp != "123456":
            retries = state.get("otp_retries", 0) + 1
            # If OTP is wrong, decide to retry or terminate based on attempts
            return {"otp_retries": retries, "decision": "terminate" if retries >= 3 else "retry"}

        # If OTP is correct, proceed to the next step
        return {"decision": "proceed"}
    
    @traceable
    def _verify_from_uidai(self, state: AadharGraphState) -> AadharGraphState:
        """Verifies the Aadhaar number against the UIDAI database after a correct OTP."""
        aadhaar_number = state["verified_data"]["aadhar_number"]
        result = aadhar_tools.verify_aadhaar_in_database(aadhaar_number)
        
        if result.status == "success":
            # Database lookup was successful
            return {"decision": "proceed", "verified_data": result.verified_data.model_dump()}
        else:
            # Database lookup failed (Aadhaar number not found)
            return {"decision": "db_failure"}


    @traceable
    def _handle_invalid_format_aa_no(self, state: AadharGraphState) -> AadharGraphState:
        retries = state.get("retries", 0) + 1
        return {
            "retries": retries, 
            "decision": "terminate" if retries >= 2 else "retry", 
            "last_executed_node":"handle_invalid_format_aa_no"
        }
    
    @traceable
    def _validate_otp_format(self, state: AadharGraphState) -> AadharGraphState:
        """Checks if the provided OTP has a valid format (6 digits)."""
        otp = state.get("user_message", "")
        if aadhar_tools.validate_otp_format(otp):
            return {"decision": "valid", "last_executed_node": "validate_otp_format"}
        else:
            return {"decision": "invalid", "last_executed_node": "validate_otp_format"}

    @traceable
    def _handle_invalid_otp_format(self, state: AadharGraphState) -> AadharGraphState:
        """Handles the case where the user enters an OTP in an invalid format."""
        retries = state.get("otp_retries", 0) + 1
        decision = "terminate" if retries >= 2 else "retry"
        
        if decision == "retry":
            message = "That doesn't look like a valid 6-digit OTP. Please try again."
        else:
            message = "I'm sorry, we couldn't validate the OTP format after multiple attempts."
            
        return {
            "otp_retries": retries, 
            "decision": decision, 
            "response_to_user": message,
            "last_executed_node":"handle_invalid_otp_format"
        }
    
    @traceable
    def _handle_db_failure(self, state: AadharGraphState) -> AadharGraphState:
        """Handles the case where Aadhaar verification fails at the database level."""
        message = (
            "Although the OTP was correct, we could not find your Aadhaar number in the official database. We cannot proceed with this verification."
            "If you have entered a wrong Aadhaar number you can restart Aadhaar verification"
            "Do you want to start aadhaar verification."
        )
        return {
            "response_to_user": message,
            "status": "END", 
            "last_executed_node": "handle_db_failure"
        }

    @traceable
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

    def _decide_after_confirmation(self, state: AadharGraphState) -> Literal["proceed", "mismatch"]:
        return "proceed" if "yes" in state["user_message"].lower() else "mismatch"
    
    @traceable
    def _handle_data_mismatch(self, state: AadharGraphState) -> AadharGraphState:
        message = (
            "I understand. Since the details retrieved from the official Aadhaar database are not correct, "
            "we cannot proceed with the automated process. We advise you to get your Aadhaar details corrected. "
            "For now, we will have to terminate this verification."
        )
        return {
            "response_to_user": message, 
            "last_executed_node": "handle_data_mismatch"
        }

    @traceable
    def _finish_aadhaar_process(self, state: AadharGraphState) -> AadharGraphState:
        message = "Thank you. Your Aadhaar details have been successfully confirmed."
        return {
            "response_to_user": message,
            "verified_data": state["verified_data"], # Pass data through
            "status": "SUCCESS",
            "last_executed_node": "finish_aadhaar_process"
        }

    @traceable
    def _terminate_workflow(self, state: AadharGraphState) -> AadharGraphState:
        message = "I'm sorry, we couldn't verify your Aadhaar details after multiple attempts. Please contact support for assistance."
        return {
            "response_to_user": message,
            "last_executed_node": "terminate_workflow",
            "status": "FAILURE",
        }

    @traceable
    def _suggest_next_steps(self, state: OverallState) -> str:
        completed: Set[str] = set(state.get("completed_workflows", []))
        # This check is now done in handle_step, but we keep it here for robustness
        if "aadhaar" not in completed:
             completed.add("aadhaar")
        remaining_docs = self.all_workflows - completed

        if "pan" in remaining_docs:
            return f"If you have a PAN card we can proceed with your PAN verification now?\nDo you have one?"
        
        remaining_docs = list(remaining_docs)
        remaining_docs.sort()
        next_doc = list(remaining_docs)[0].upper()
        
        if "FORM60" in next_doc:
            return "You have now completed all required document verifications!"
            
        if not remaining_docs:
            return "You have now completed all required document verifications!"
        