'''# THE SUGGEST NEXT STEP IS HANDLED IN SUCH A WAY EITHER BOTH PAN AND FORM60 
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
from prompts.aadhar_prompts import (
    AADHAR_REQUEST_PROMPT,
    AADHAR_RETRY_PROMPT,
    OTP_REQUEST_PROMPT,
    OTP_RETRY_PROMPT,
    DB_VERIFICATION_FAILED,
    CONFIRMATION_PROMPT,
    DATA_MISMATCH_PROMPT,
    VERIFICATION_SUCCESS,
    VERIFICATION_TERMINATED
)

class AadharAgent(BaseSpecialistAgent):
    """
    An expert agent for Aadhaar verification, implemented as a robust, interruptible LangGraph state machine.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60", "passport", "dl"}
        self.llm_client = LLMFactory()
        
        builder = StateGraph(AadharGraphState)

        # --- Node Definitions ---
        builder.add_node("choose_method", self._choose_method)
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
        builder.add_edge(START, "choose_method")
        builder.add_edge("choose_method", "prompt_for_aadhaar")
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
                "db_failure": "terminate_workflow"     # If DB lookup fails, handle that specific failure
            }
        )
        
        builder.add_conditional_edges(
            "prompt_for_confirmation",
            self._decide_after_confirmation,
            {
                "proceed": "finish_aadhaar_process",
                "terminate": "terminate_workflow"
            }
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
                next_step = self._suggest_next_steps(state)
                final_graph_state["response_to_user"] += "\n" + next_step
            
                verified_data = final_graph_state["verified_data"]
                state["aadhar_details"] = AadharDetailsState(
                    aadhar_number=verified_data["aadhar_number"],
                    name=verified_data["name"],
                    date_of_birth=verified_data["date_of_birth"],
                    address=verified_data["address"],
                    new_doc_needed=False
                )
                state["aadhar_verification_status"] = VerificationState(
                    verification_status="success",
                    verification_message="Aadhaar details successfully verified from database.",
                    verification_timestamp=datetime.datetime.now().isoformat(),
                    verification_doc="Aadhaar e-Verification"
                )

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    @traceable
    def _choose_method(self, state: AadharGraphState) -> AadharGraphState:
        message = "Please choose a method to verify your Aadhaar: (e-KYC/Digilocker)"
        return {
            "response_to_user": message,
            "last_executed_node": "choose_method"
        }
    
    @traceable
    def _prompt_for_aadhaar(self, state: AadharGraphState) -> AadharGraphState:
        message = AADHAR_RETRY_PROMPT if state.get("retries", 0) > 0 else AADHAR_REQUEST_PROMPT
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_aadhaar"
        }
    
    @traceable
    def _prompt_for_otp(self, state: AadharGraphState) -> AadharGraphState:
        message = OTP_RETRY_PROMPT if state.get("otp_retries", 0) > 0 else OTP_REQUEST_PROMPT
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
        return {
            "response_to_user": DB_VERIFICATION_FAILED,
            "status": "END", 
            "last_executed_node": "handle_db_failure"
        }

    @traceable
    def _prompt_for_confirmation(self, state: AadharGraphState) -> AadharGraphState:
        verified_data = state["verified_data"]
        message = CONFIRMATION_PROMPT.format(
            name=verified_data['name'],
            dob=verified_data['date_of_birth'],
            aadhar=verified_data['aadhar_number'],
            address=verified_data['address']
        )
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }

    def _decide_after_confirmation(self, state: AadharGraphState) -> Literal["proceed", "mismatch"]:
        if "yes" in state["user_message"].lower():
            return "proceed"
        else:
            return "terminate"

    @traceable
    def _handle_data_mismatch(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": DATA_MISMATCH_PROMPT, 
            "last_executed_node": "handle_data_mismatch"
        }

    @traceable
    def _finish_aadhaar_process(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": VERIFICATION_SUCCESS,
            "verified_data": state["verified_data"], # Pass data through
            "status": "SUCCESS",
            "last_executed_node": "finish_aadhaar_process"
        }

    @traceable
    def _terminate_workflow(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": VERIFICATION_TERMINATED,
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
            return "You have now completed all required document verifications!"'''

import datetime
from typing import Literal, Set
import time
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver # Use a persistent checkpointer in production
from langgraph.types import Command, Interrupt
from langsmith import traceable

# Assuming these are in the correct paths
from agent.base_agent import BaseSpecialistAgent
from tools import aadhar_tools
from state import OverallState, AadharGraphState, AadharDetailsState, VerificationState
from llm import LLMFactory
from tools.ocr_tool import OCR
from api.ocr_api import DocumentIntelligenceService
from prompts.aadhar_prompts import (
    AADHAR_REQUEST_PROMPT,
    AADHAR_RETRY_PROMPT,
    OTP_REQUEST_PROMPT,
    OTP_RETRY_PROMPT,
    DB_VERIFICATION_FAILED,
    CONFIRMATION_PROMPT,
    DATA_MISMATCH_PROMPT,
    VERIFICATION_SUCCESS,
    VERIFICATION_TERMINATED
)

class AadharAgent(BaseSpecialistAgent):
    """
    An expert agent for Aadhaar verification, implemented as a robust, interruptible LangGraph state machine.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60", "passport", "dl"}
        self.llm_client = LLMFactory()
        self.full_workflow_retry = 0  # Added for image processing retry counter
        
        # OCR related components
        self.ocr = OCR()
        self.ocr_real = DocumentIntelligenceService()
        
        builder = StateGraph(AadharGraphState)

        # --- Node Definitions ---
        builder.add_node("choose_method", self._choose_method)
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

        # --- NEW IMAGE PROCESSING NODES ---
        builder.add_node("accept_aadhar_image", self._accept_aadhar_image)
        builder.add_node("aadhar_ocr_extract", self._aadhar_ocr_extract)
        builder.add_node("display_aadhar_details", self._display_aadhar_details)
        builder.add_node("acknowledge_aadhar_details", self._acknowledge_aadhar_details)

        # --- Edge Definitions ---
        builder.add_edge(START, "choose_method")
        builder.add_edge("choose_method", "prompt_for_aadhaar")
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

        # MODIFIED: Route to image acceptance instead of direct termination on DB failure
        builder.add_conditional_edges(
            "verify_from_uidai",
            lambda s: s.get("decision"),
            {
                "proceed": "prompt_for_confirmation", # If DB lookup succeeds, ask for confirmation
                "db_failure": "accept_aadhar_image"   # If DB lookup fails, try image verification
            }
        )
        
        builder.add_conditional_edges(
            "prompt_for_confirmation",
            self._decide_after_confirmation,
            {
                "proceed": "finish_aadhaar_process",
                "terminate": "terminate_workflow"
            }
        )

        # --- NEW IMAGE PROCESSING EDGES ---
        builder.add_edge("accept_aadhar_image", "aadhar_ocr_extract")
        
        builder.add_conditional_edges(
            "aadhar_ocr_extract",
            lambda s: s.get("decision"),
            {"proceed": "display_aadhar_details", "terminate": "terminate_workflow"}
        )
        
        builder.add_edge("display_aadhar_details", "acknowledge_aadhar_details")
        
        builder.add_conditional_edges(
            "acknowledge_aadhar_details",
            lambda s: s.get("decision"),
            {
                "retry": "accept_aadhar_image", 
                "proceed": "prompt_for_confirmation",  # Go to confirmation with OCR data
                "terminate": "terminate_workflow"
            }
        )

        builder.add_edge("finish_aadhaar_process", END)
        builder.add_edge("terminate_workflow", END)
        builder.add_edge("handle_data_mismatch", END) 
        
        # --- Graph Compilation with UPDATED Interruption Pattern ---
        checkpointer = InMemorySaver()
        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after=["choose_method", "prompt_for_aadhaar", "prompt_for_confirmation", "prompt_for_otp", 
                           "accept_aadhar_image", "display_aadhar_details"]
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

        # UPDATED: Added new KYC steps for image processing
        if last_node == "prompt_for_aadhaar":
            state["kyc_step"] = "awaiting_aadhaar_input"
        elif last_node == "prompt_for_otp":
            state["kyc_step"] = "awaiting_otp_input"
        elif last_node == "prompt_for_confirmation":
            state["kyc_step"] = "awaiting_aadhaar_confirmation"
        elif last_node == "accept_aadhar_image":
            state["kyc_step"] = "awaiting_aadhar_image"
        elif last_node == "display_aadhar_details":
            state["kyc_step"] = "awaiting_aadhar_details_acknowledgement"
        else:
            state["kyc_step"] = None

        if final_graph_state.get("status") in ["SUCCESS", "FAILURE"]:
            # Mark the workflow as "completed" so the orchestrator doesn't ask again.
            if "aadhaar" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["aadhaar"]
            
            state["active_workflow"] = None
            state["kyc_step"] = None

            # If it was a success, update state and suggest next steps
            if final_graph_state.get("status") == "SUCCESS":
                state["completed_workflows"] = state.get("completed_workflows", []) + ["passport", "dl"]
                next_step = self._suggest_next_steps(state)
                final_graph_state["response_to_user"] += "\n" + next_step
            
                verified_data = final_graph_state["verified_data"]
                state["aadhar_details"] = AadharDetailsState(
                    aadhar_number=verified_data["aadhar_number"],
                    name=verified_data["name"],
                    date_of_birth=verified_data["date_of_birth"],
                    address=verified_data["address"],
                    new_doc_needed=False
                )
                state["aadhar_verification_status"] = VerificationState(
                    verification_status="success",
                    verification_message="Aadhaar details successfully verified from database.",
                    verification_timestamp=datetime.datetime.now().isoformat(),
                    verification_doc="Aadhaar e-Verification"
                )

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    @traceable
    def _choose_method(self, state: AadharGraphState) -> AadharGraphState:
        message = "Please choose a method to verify your Aadhaar: (e-KYC/Digilocker)"
        return {
            "response_to_user": message,
            "last_executed_node": "choose_method"
        }
    
    @traceable
    def _prompt_for_aadhaar(self, state: AadharGraphState) -> AadharGraphState:
        message = AADHAR_RETRY_PROMPT if state.get("retries", 0) > 0 else AADHAR_REQUEST_PROMPT
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_aadhaar"
        }
    
    @traceable
    def _prompt_for_otp(self, state: AadharGraphState) -> AadharGraphState:
        message = OTP_RETRY_PROMPT if state.get("otp_retries", 0) > 0 else OTP_REQUEST_PROMPT
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
            # Database lookup failed - route to image verification instead of terminating
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
        return {
            "response_to_user": DB_VERIFICATION_FAILED,
            "status": "END", 
            "last_executed_node": "handle_db_failure"
        }

    # --- NEW IMAGE PROCESSING METHODS ---
    
    @traceable
    def _accept_aadhar_image(self, state: AadharGraphState) -> AadharGraphState:
        """Prompts user to upload Aadhaar card image for OCR processing."""
        if self.full_workflow_retry == 0:
            message = """The database verification didn't work. Let's try with your Aadhaar card image.

Please upload a clear photo of your Aadhaar card (front side). Make sure:
- The image is clear and well-lit
- All text is readable
- The card is flat and fully visible"""
        else:
            message = """Let's try again with a clearer image.

Please re-upload your Aadhaar card photo ensuring:
- Better lighting and focus
- All details are clearly visible
- The image is not blurry or tilted"""
            
        return {
            "response_to_user": message,
            "last_executed_node": "accept_aadhar_image"
        }
    
    @traceable
    def _aadhar_ocr_extract(self, state: AadharGraphState) -> AadharGraphState:
        """Processes the uploaded Aadhaar card image using OCR."""
        print("Processing Aadhaar card image...")
        self.full_workflow_retry += 1
        
        time.sleep(2.0)  # Simulate processing time
        
        if self.full_workflow_retry < 2:  # Allow up to 2 retries
            # Mock OCR response (in production, replace with actual OCR call)
            mock_details = {
                "aadhar_number": "123456789012",
                "name": "Ananya Sharma",
                "date_of_birth": "01/01/1990",
                "address": "12A, MG Road, Near Central Park, Connaught Place, New Delhi, 110001"
            }

            return {
                "response_to_user": "Aadhaar card image processed successfully. Let me show you the extracted details.",
                "last_executed_node": "aadhar_ocr_extract",
                "verified_data": mock_details,
                "decision": "proceed"
            }
        else:
            return {
                "response_to_user": "I'm having trouble processing your Aadhaar card image. Please contact customer support for assistance.",
                "last_executed_node": "aadhar_ocr_extract",
                "decision": "terminate"
            }

    @traceable
    def _display_aadhar_details(self, state: AadharGraphState) -> AadharGraphState:
        """Displays the extracted Aadhaar details for user confirmation."""
        verified_data = state["verified_data"]
        message = f"""Here are the details extracted from your Aadhaar card:

**Aadhaar Number:** {verified_data["aadhar_number"]}
**Name:** {verified_data["name"]}
**Date of Birth:** {verified_data["date_of_birth"]}
**Address:** {verified_data["address"]}

Are these details correct? Please reply with:
- **YES** if all details are correct
- **NO** if you want to try uploading the image again"""
        
        return {
            "response_to_user": message,
            "last_executed_node": "display_aadhar_details"
        }

    @traceable
    def _acknowledge_aadhar_details(self, state: AadharGraphState) -> AadharGraphState:
        """Handles user's response to the displayed Aadhaar details."""
        user_response = state["user_message"].lower().strip()
        
        if "yes" in user_response:
            return {
                "decision": "proceed", 
                "verified_data": state["verified_data"],
                "last_executed_node": "acknowledge_aadhar_details"
            }
        elif "no" in user_response and self.full_workflow_retry < 2:
            return {
                "decision": "retry",
                "last_executed_node": "acknowledge_aadhar_details"
            }
        else:
            return {
                "decision": "terminate",
                "last_executed_node": "acknowledge_aadhar_details"
            }

    @traceable
    def _prompt_for_confirmation(self, state: AadharGraphState) -> AadharGraphState:
        verified_data = state["verified_data"]
        message = CONFIRMATION_PROMPT.format(
            name=verified_data['name'],
            dob=verified_data['date_of_birth'],
            aadhar=verified_data['aadhar_number'],
            address=verified_data['address']
        )
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }

    def _decide_after_confirmation(self, state: AadharGraphState) -> Literal["proceed", "terminate"]:
        if "yes" in state["user_message"].lower():
            return "proceed"
        else:
            return "terminate"

    @traceable
    def _handle_data_mismatch(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": DATA_MISMATCH_PROMPT, 
            "last_executed_node": "handle_data_mismatch"
        }

    @traceable
    def _finish_aadhaar_process(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": VERIFICATION_SUCCESS,
            "verified_data": state["verified_data"], # Pass data through
            "status": "SUCCESS",
            "last_executed_node": "finish_aadhaar_process"
        }

    @traceable
    def _terminate_workflow(self, state: AadharGraphState) -> AadharGraphState:
        return {
            "response_to_user": VERIFICATION_TERMINATED,
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