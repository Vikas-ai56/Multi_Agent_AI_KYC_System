'''# Currently there is no limit for retries after
# acknowledgement NO from the user during "prompt_for_confirmation"
# THE OCR is a spoofed version only

import datetime
from typing import Tuple, Literal, Set
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver  
from langgraph.types import Interrupt, Command
from pydantic import BaseModel, Field
from typing_extensions import Optional
from langsmith import traceable

# Assuming correct import paths
from agent.base_agent import BaseSpecialistAgent
from tools import pan_tools
from state import OverallState, PanGraphState
from llm import LLMFactory
from tools.ocr_tool import OCR
from tools.ocr_pan_tool import PanProcessor
from api.ocr_api import DocumentIntelligenceService
from prompts.pan_prompts import (
    PAN_PREFILLED_PROMPT,
    PAN_MANUAL_PROMPT,
    PAN_MANUAL_RETRY_PROMPT,
    PAN_CORRECTION_PROMPT,
    PAN_CONFIRMATION_PROMPT,
    PAN_VERIFICATION_SUCCESS,
    PAN_VERIFICATION_FAILED,
    PAN_OCR_REQUEST,
    PAN_TERMINATION
)

class ParsedPANDetailsState(BaseModel):
    pan_card_number: str = Field(description="The PAN card number of the user")
    date_of_birth: str = Field(description="THE customers date of birth in DD/MM/YYYY format")
    pan_card_holders_name: str = Field(description="The name of the user as written on the PAN card")

class PanAgent(BaseSpecialistAgent):
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        self.ocr = OCR()
        self.correction = False

        self.ocr_real = DocumentIntelligenceService()
        self.pan_ocr_processor = PanProcessor()

        # self.source = Path(r"/Users/administrator/newfinal3/Multi_Agent_AI_KYC_System/test_pan.jpeg")
        builder = StateGraph(PanGraphState)
        
        # Node and Edge definitions from your code are correct, no changes needed here.
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        self.nsdl_verification_count = 0

        builder = StateGraph(PanGraphState)

        builder.add_node("check_aadhaar_dependency", self._check_aadhaar_dependency)

        builder.add_node("prompt_for_pan_prefilled", self._prompt_for_pan_prefilled)

        builder.add_node("prompt_for_pan_manual", self._prompt_for_pan_manual)
        builder.add_node("collect_manual_details", self._collect_manual_details)

        builder.add_node("validate_pan_input", self._validate_pan_input)

        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)

        builder.add_node("verify_with_nsdl", self._verify_with_nsdl)

        builder.add_node("handle_invalid_pan_format", self._handle_invalid_pan_format)

        builder.add_node("accept_pan_image", self._accept_pan_image)
        builder.add_node("pan_ocr_extract", self._pan_ocr_extract)

        builder.add_node("finish_pan_process", self._finish_pan_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)
        builder.add_node("prepare_for_manual_correction", self._prepare_for_manual_correction)

        # This edge and the it's node is just a flag function to start the graph workflow
        builder.add_edge(START, "check_aadhaar_dependency")

        builder.add_conditional_edges(
            "check_aadhaar_dependency",
            lambda s: "manual" if not s.get("aadhaar_details") else "prefilled",
            {"manual": "prompt_for_pan_manual", "prefilled": "prompt_for_pan_prefilled"}
        )

        builder.add_edge("prompt_for_pan_prefilled", "validate_pan_input")
        builder.add_edge("prompt_for_pan_manual", "collect_manual_details")

        builder.add_conditional_edges(
            "collect_manual_details",
            lambda s: "proceed" if s.get("pan_details", {}).get("pan_card_number") else "retry",
            {"proceed": "validate_pan_input", "retry": "prompt_for_pan_manual"}
        )
        
        builder.add_conditional_edges(
            "validate_pan_input",
            lambda s: s.get("decision"),
            {"proceed": "prompt_for_confirmation", "retry": "handle_invalid_pan_format"}
        )
        
        builder.add_conditional_edges(
            "handle_invalid_pan_format",
            lambda s: s.get("decision"),
            {"retry": "prompt_for_pan_prefilled", "terminate": "terminate_workflow"}
        )
        
        # This node will now pause. After resuming, it will route based on the user's reply.
        builder.add_conditional_edges(
            "prompt_for_confirmation",
            self._decide_after_confirmation,
            # Changes made for the re-routing part when the decision is terminate
            {"proceed": "verify_with_nsdl", "correction": "prepare_for_manual_correction"}
        )

        builder.add_edge("prepare_for_manual_correction", "prompt_for_pan_manual")
        
        builder.add_conditional_edges(
            "verify_with_nsdl",
            lambda s: s.get("decision"),
            {"success": "finish_pan_process", "failure": "accept_pan_image"}
        )

        builder.add_edge("accept_pan_image", "pan_ocr_extract")

        builder.add_conditional_edges(
            "pan_ocr_extract",
            lambda s: s.get("decision"),
            {"retry":"verify_with_nsdl", "terminate":"terminate_workflow"}
        )

        builder.add_edge("finish_pan_process", END)
        builder.add_edge("terminate_workflow", END)

        # Graph Compilation with Interruption 
        checkpointer = InMemorySaver()
        interrupt_after = ["prompt_for_confirmation", "prompt_for_pan_prefilled", "prompt_for_pan_manual", "accept_pan_image"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )

    @traceable(name="PAN_AGENT_HANDLE_STEP")
    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None

        if checkpoint and checkpoint.next:
            # Resume graph after interrupt
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
            # Fresh start
            graph_input = PanGraphState(
                session_id=state["session_id"],
                user_message=user_message,
                aadhaar_details=state.get("aadhar_details"),
                pan_details=state.get("pan_details", {}),
                retries=state.get("pan_retries", 0),
                last_executed_node="",
                response_to_user="",
                status="IN_PROGRESS",
                decision=None,
            )

            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        state["pan_details"] = final_graph_state.get("pan_details", {})
        state["pan_retries"] = final_graph_state.get("retries", 0)
        last_node = final_graph_state.get("last_executed_node")

        if last_node == "prompt_for_pan_prefilled":
            state["kyc_step"] = "awaiting_pan_input_prefilled"
        elif last_node == "prompt_for_pan_manual":
            state["kyc_step"] = "awaiting_pan_input_manual"
        elif last_node == "prompt_for_confirmation":
            state["kyc_step"] = "awaiting_pan_confirmation"
        else:
            state["kyc_step"] = None
            state["active_workflow"] = None

        if final_graph_state.get("status","") == "SUCCESS":
            if "pan" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]
                
            state["active_workflow"] = None
            state["kyc_step"] = None
            next_step = self._suggest_next_steps(state)
            final_graph_state["response_to_user"] += "\n" + next_step

        elif final_graph_state.get("status","") == "FAILURE":
            if "pan" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]
             
            state["active_workflow"] = None
            state["kyc_step"] = None   

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    def _check_aadhaar_dependency(self, state: PanGraphState) -> PanGraphState:
        return {} # Only return changes

    @traceable
    def _prompt_for_pan_prefilled(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_PREFILLED_PROMPT,
            "last_executed_node": "prompt_for_pan_prefilled"
        }
    
    @traceable
    def _prompt_for_pan_manual(self, state: PanGraphState) -> PanGraphState:
        if state.get("decision") == "correction":
            message = PAN_CORRECTION_PROMPT
        elif state.get("retries", 0) > 0:
            message = PAN_MANUAL_RETRY_PROMPT
        else:
            message = PAN_MANUAL_PROMPT
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_pan_manual"
        }

    @traceable
    def _collect_manual_details(self, state: PanGraphState) -> PanGraphState:
        try:
            if not self.correction:
                # Parse user input with LLM
                SYSTEM_PROMPT = """
    You are an expert at extracting PAN card information from user input.
    Extract the following details from the user's message:
    - PAN card number
    - Full name of the cardholder
    - Date of birth

    The user will provide this information in various formats. Extract the actual values, not placeholder text.
    """            
                details: ParsedPANDetailsState = self.llm_client._get_structured_response(
                    human_prompt=state["user_message"],
                    parser=ParsedPANDetailsState,
                    sys_prompt=SYSTEM_PROMPT
                )

                if not details:
                    raise ValueError("Could not parse PAN details.")
                
                if details.pan_card_number:
                    details.pan_card_number = details.pan_card_number.upper()

                # Validate extracted details
                if (not details.pan_card_number or
                    not details.pan_card_holders_name or
                    not details.date_of_birth or
                    not pan_tools.validate_pan_format(details.pan_card_number)):
                    raise ValueError("Parsed details incomplete or invalid.")

                # Update state to include parsed PAN details
                new_pan_details = details.model_dump()
                return {
                    "pan_details": new_pan_details,
                    "decision": "proceed",
                    "last_executed_node": "collect_manual_details"
                }

            else:
                CORRECTION_SYSTEM_PROMPT = f"""
You are an expert at extracting PAN card information from user input.
Extract the following details from the user's message:

- PAN card number
- Full name of the cardholder
- Date of birth

Current PAN card details as entered by the user for the first time before correction:
{state["pan_details"]}

IMPORTANT:
The user will enter only the details that are incorrect. Do not make any assumptions. 
You have to assume the details are correct from the current PAN card details as entered by the user for the first time before correction.
Fill those existing details in the new PAN card details and then rewrite the incorrect ones.

NOTE: YOU HAVE TO RETURN THE COMPLETE NEW PAN CARD DETAILS AFTER CORRECTION. WHILE THE EXISTING DETAILS ARE UNALTERED.
"""
                details: ParsedPANDetailsState = self.llm_client._get_structured_response(
                    human_prompt=state["user_message"],
                    parser=ParsedPANDetailsState,
                    sys_prompt=CORRECTION_SYSTEM_PROMPT
                )

                print(details)

                if not details:
                    raise ValueError("Could not parse PAN details.")
                
                if details.pan_card_number:
                    details.pan_card_number = details.pan_card_number.upper()

                # Validate extracted details
                if (not details.pan_card_number or
                    not details.pan_card_holders_name or
                    not details.date_of_birth or
                    not pan_tools.validate_pan_format(details.pan_card_number)):
                    raise ValueError("Parsed details incomplete or invalid.")

                # Update state to include parsed PAN details
                new_pan_details = details.model_dump()
                return {
                    "pan_details": new_pan_details,
                    "decision": "proceed",
                    "last_executed_node": "collect_manual_details"
                }

        except Exception as e:
            # Log parsing error for debugging
            print(f"PAN details parsing failed: {e}")

            # Increase retry count and clear details to force retry path
            retries = state.get("retries", 0) + 1
            return {
                "pan_details": {},
                "retries": retries,
                "decision": "retry",
                "last_executed_node": "collect_manual_details"
            }

    @traceable
    def _validate_pan_input(self, state: PanGraphState) -> PanGraphState:
        if state["last_executed_node"] == "collect_manual_details":
            pan_number = state["pan_details"]["pan_card_number"].strip().upper()
# -------------------------------------------------------------------------------------
# FOR PAN PREFILLED OPTION
# -------------------------------------------------------------------------------------
        else:
            pan_number = state["user_message"].strip().upper()
        
        if not pan_tools.validate_pan_format(pan_number):
            return {
                "decision": "retry",
                "retries": state.get("retries", 0) + 1
            }
        
        if state.get("aadhaar_details"):
            pan_details = {
                "pan_card_number": pan_number,
                "date_of_birth": state["aadhaar_details"]["date_of_birth"],
                "pan_card_holders_name": state["aadhaar_details"]["name"]
            }
            return {
                "decision": "proceed",
                "pan_details": pan_details,
                "last_executed_node": "validate_pan_input"
            }
        return {
            "decision": "proceed",
            "last_executed_node": "validate_pan_input"
        }

    def _prompt_for_confirmation(self, state: PanGraphState) -> PanGraphState:
        message = PAN_CONFIRMATION_PROMPT.format(
            pan=state['pan_details']['pan_card_number'],
            name=state['pan_details']['pan_card_holders_name'],
            dob=state['pan_details']['date_of_birth']
        )
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }
    
    @traceable
    def _prepare_for_manual_correction(self, state: PanGraphState) -> PanGraphState:
        # This node clears details and sets the decision for the next prompt.
        self.correction = True
        return {
            "pan_details": state["pan_details"],
            "decision": "correction",
            "last_executed_node": "prepare_for_manual_correction"
        }
    
    def _decide_after_confirmation(self, state: PanGraphState) -> Literal["proceed", "correction"]:
        return "proceed" if "yes" in state["user_message"].lower() else "correction"

    @traceable
    def _verify_with_nsdl(self, state: PanGraphState) -> PanGraphState:
        self.nsdl_verification_count += 1

        nsdl_result = pan_tools.verify_pan_in_nsdl(state["pan_details"])
        is_match = not state.get("aadhaar_details") or (
            nsdl_result.status == "success" and
            pan_tools.compare_pan_and_aadhaar_data(state["pan_details"], state["aadhaar_details"])
        )
        
        decision = "success" if nsdl_result.status == "success" and self.nsdl_verification_count < 3 and is_match else "failure"
        
        return {
            "decision": decision,
            "last_executed_node": "verify_with_nsdl"
        }
    
    @traceable
    def _accept_pan_image(self, state:PanGraphState) -> PanGraphState:
        {
            "response_to_user": "No Worries, Please re-upload your PAN card's Image\nPlease make sure it is clear and legible.",
            "last_executed_node": "accept_pan_image",
            "pan_details":{}
        }
    
    @traceable
    def _pan_ocr_extract(self, state: PanGraphState) -> PanGraphState:
        if self.nsdl_verification_count < 3:
            print("Processing PAN card image...")
            
            # Mock OCR response instead of real API call
            mock_details = {
                "permanent_account_number": "ABCDE1234F",
                "date_of_birth": "01/01/1990",
                "name": "Ananya Sharma"
            }
            
            state["pan_details"] = {
                "pan_card_number": mock_details["permanent_account_number"],
                "date_of_birth": mock_details["date_of_birth"],
                "pan_card_holders_name": mock_details["name"]
            }

            return {
                "response_to_user": "PAN card image processed successfully. Let me verify these details.",
                "last_executed_node": "pan_ocr_extract",
                "pan_details": state["pan_details"],
                "decision": "retry"
            }

        else:
            return {
                "response_to_user": PAN_VERIFICATION_FAILED,
                "last_executed_node": "pan_ocr_extract",
                "decision": "terminate"
            }
       
    def _handle_invalid_pan_format(self, state: PanGraphState) -> PanGraphState:
        retries = state.get("retries", 0) + 1
        decision = "terminate" if retries >= 2 else "retry"
        return {
            "retries": retries,
            "decision": decision,
            "last_executed_node": "handle_invalid_pan_format"
        }
    
    @traceable
    def _finish_pan_process(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_VERIFICATION_SUCCESS,
            "status": "SUCCESS",
            "last_executed_node": "finish_pan_process"
        }

    def _terminate_workflow(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_TERMINATION,
            "status": "FAILURE",
            "last_executed_node": "terminate_workflow"
        }
    
    def _suggest_next_steps(self, state: OverallState) -> str:
        completed: Set[str] = set(state.get("completed_workflows", []))
        if "pan" not in completed:
             completed.add("pan")
        remaining_docs = self.all_workflows - completed

        if not remaining_docs:
            return "You have now completed all required document verifications!"
        
        remaining_docs = list(remaining_docs)
        remaining_docs.sort()
        next_doc = list(remaining_docs)[0].upper()

        if "FORM60" in next_doc:
            return "You have now completed all required document verifications!"
        else:
            return f"Would you like to proceed with your {next_doc} verification now?"'''

import datetime
from typing import Tuple, Literal, Set
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver  
from langgraph.types import Interrupt, Command
from pydantic import BaseModel, Field
from typing_extensions import Optional
from langsmith import traceable
import time

# Assuming correct import paths
from agent.base_agent import BaseSpecialistAgent
from tools import pan_tools
from state import OverallState, PanGraphState
from llm import LLMFactory
from tools.ocr_tool import OCR
from tools.ocr_pan_tool import PanProcessor
from api.ocr_api import DocumentIntelligenceService
from prompts.pan_prompts import (
    PAN_PREFILLED_PROMPT,
    PAN_MANUAL_PROMPT,
    PAN_MANUAL_RETRY_PROMPT,
    PAN_CORRECTION_PROMPT,
    PAN_CONFIRMATION_PROMPT,
    PAN_VERIFICATION_SUCCESS,
    PAN_VERIFICATION_FAILED,
    PAN_OCR_REQUEST,
    PAN_TERMINATION
)

class ParsedPANDetailsState(BaseModel):
    pan_card_number: str = Field(description="The PAN card number of the user")
    date_of_birth: str = Field(description="THE customers date of birth in DD/MM/YYYY format")
    pan_card_holders_name: str = Field(description="The name of the user as written on the PAN card")

class PanAgent(BaseSpecialistAgent):
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        self.ocr = OCR()
        self.correction = False
        self.full_workflow_retry = 0  # Added similar to DL agent

        self.ocr_real = DocumentIntelligenceService()
        self.pan_ocr_processor = PanProcessor()

        # self.source = Path(r"/Users/administrator/newfinal3/Multi_Agent_AI_KYC_System/test_pan.jpeg")
        builder = StateGraph(PanGraphState)
        
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        self.nsdl_verification_count = 0

        builder = StateGraph(PanGraphState)

        builder.add_node("check_aadhaar_dependency", self._check_aadhaar_dependency)
        builder.add_node("prompt_for_pan_prefilled", self._prompt_for_pan_prefilled)
        builder.add_node("prompt_for_pan_manual", self._prompt_for_pan_manual)
        builder.add_node("collect_manual_details", self._collect_manual_details)
        builder.add_node("validate_pan_input", self._validate_pan_input)
        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)
        builder.add_node("verify_with_nsdl", self._verify_with_nsdl)
        builder.add_node("handle_invalid_pan_format", self._handle_invalid_pan_format)
        
        # Added new nodes for image processing similar to DL agent
        builder.add_node("accept_pan_image", self._accept_pan_image)
        builder.add_node("pan_ocr_extract", self._pan_ocr_extract)
        builder.add_node("display_pan_details", self._display_pan_details)
        builder.add_node("acknowledge_pan_details", self._acknowledge_pan_details)
        
        builder.add_node("finish_pan_process", self._finish_pan_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)
        builder.add_node("prepare_for_manual_correction", self._prepare_for_manual_correction)

        # This edge and the it's node is just a flag function to start the graph workflow
        builder.add_edge(START, "check_aadhaar_dependency")

        builder.add_conditional_edges(
            "check_aadhaar_dependency",
            lambda s: "manual" if not s.get("aadhaar_details") else "prefilled",
            {"manual": "prompt_for_pan_manual", "prefilled": "prompt_for_pan_prefilled"}
        )

        builder.add_edge("prompt_for_pan_prefilled", "validate_pan_input")
        builder.add_edge("prompt_for_pan_manual", "collect_manual_details")

        builder.add_conditional_edges(
            "collect_manual_details",
            lambda s: "proceed" if s.get("pan_details", {}).get("pan_card_number") else "retry",
            {"proceed": "validate_pan_input", "retry": "prompt_for_pan_manual"}
        )
        
        builder.add_conditional_edges(
            "validate_pan_input",
            lambda s: s.get("decision"),
            {"proceed": "prompt_for_confirmation", "retry": "handle_invalid_pan_format"}
        )
        
        builder.add_conditional_edges(
            "handle_invalid_pan_format",
            lambda s: s.get("decision"),
            {"retry": "prompt_for_pan_prefilled", "terminate": "terminate_workflow"}
        )
        
        # This node will now pause. After resuming, it will route based on the user's reply.
        builder.add_conditional_edges(
            "prompt_for_confirmation",
            self._decide_after_confirmation,
            # Changes made for the re-routing part when the decision is terminate
            {"proceed": "verify_with_nsdl", "correction": "prepare_for_manual_correction"}
        )

        builder.add_edge("prepare_for_manual_correction", "prompt_for_pan_manual")
        
        builder.add_conditional_edges(
            "verify_with_nsdl",
            lambda s: s.get("decision"),
            # Modified to route to image acceptance instead of direct OCR
            {"success": "finish_pan_process", "failure": "accept_pan_image"}
        )

        # Added edges for image processing workflow
        builder.add_edge("accept_pan_image", "pan_ocr_extract")
        
        builder.add_conditional_edges(
            "pan_ocr_extract",
            lambda s: s.get("decision"),
            {"proceed": "display_pan_details", "terminate": "terminate_workflow"}
        )
        
        builder.add_edge("display_pan_details", "acknowledge_pan_details")
        
        builder.add_conditional_edges(
            "acknowledge_pan_details",
            lambda s: s.get("decision"),
            {"retry": "accept_pan_image", "proceed": "verify_with_nsdl", "terminate": "terminate_workflow"}
        )

        builder.add_edge("finish_pan_process", END)
        builder.add_edge("terminate_workflow", END)

        # Graph Compilation with Interruption - Added new interrupt nodes
        checkpointer = InMemorySaver()
        interrupt_after = ["prompt_for_confirmation", "prompt_for_pan_prefilled", "prompt_for_pan_manual", 
                          "accept_pan_image", "display_pan_details"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )

    @traceable(name="PAN_AGENT_HANDLE_STEP")
    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None

        if checkpoint and checkpoint.next:
            # Resume graph after interrupt
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
            # Fresh start
            graph_input = PanGraphState(
                session_id=state["session_id"],
                user_message=user_message,
                aadhaar_details=state.get("aadhar_details"),
                pan_details=state.get("pan_details", {}),
                retries=state.get("pan_retries", 0),
                last_executed_node="",
                response_to_user="",
                status="IN_PROGRESS",
                decision=None,
            )

            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        state["pan_details"] = final_graph_state.get("pan_details", {})
        state["pan_retries"] = final_graph_state.get("retries", 0)
        last_node = final_graph_state.get("last_executed_node")

        # Updated to handle new image-related steps
        if last_node == "prompt_for_pan_prefilled":
            state["kyc_step"] = "awaiting_pan_input_prefilled"
        elif last_node == "prompt_for_pan_manual":
            state["kyc_step"] = "awaiting_pan_input_manual"
        elif last_node == "prompt_for_confirmation":
            state["kyc_step"] = "awaiting_pan_confirmation"
        elif last_node == "accept_pan_image":
            state["kyc_step"] = "awaiting_pan_image"
        elif last_node == "display_pan_details":
            state["kyc_step"] = "awaiting_pan_details_acknowledgement"
        else:
            state["kyc_step"] = None
            state["active_workflow"] = None

        if final_graph_state.get("status","") == "SUCCESS":
            if "pan" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]
                
            state["active_workflow"] = None
            state["kyc_step"] = None
            next_step = self._suggest_next_steps(state)
            final_graph_state["response_to_user"] += "\n" + next_step

        elif final_graph_state.get("status","") == "FAILURE":
            if "pan" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]
             
            state["active_workflow"] = None
            state["kyc_step"] = None   

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    def _check_aadhaar_dependency(self, state: PanGraphState) -> PanGraphState:
        return {} # Only return changes

    @traceable
    def _prompt_for_pan_prefilled(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_PREFILLED_PROMPT,
            "last_executed_node": "prompt_for_pan_prefilled"
        }
    
    @traceable
    def _prompt_for_pan_manual(self, state: PanGraphState) -> PanGraphState:
        if state.get("decision") == "correction":
            message = PAN_CORRECTION_PROMPT
        elif state.get("retries", 0) > 0:
            message = PAN_MANUAL_RETRY_PROMPT
        else:
            message = PAN_MANUAL_PROMPT
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_pan_manual"
        }

    @traceable
    def _collect_manual_details(self, state: PanGraphState) -> PanGraphState:
        try:
            if not self.correction:
                # Parse user input with LLM
                SYSTEM_PROMPT = """
    You are an expert at extracting PAN card information from user input.
    Extract the following details from the user's message:
    - PAN card number
    - Full name of the cardholder
    - Date of birth

    The user will provide this information in various formats. Extract the actual values, not placeholder text.
    """            
                details: ParsedPANDetailsState = self.llm_client._get_structured_response(
                    human_prompt=state["user_message"],
                    parser=ParsedPANDetailsState,
                    sys_prompt=SYSTEM_PROMPT
                )

                if not details:
                    raise ValueError("Could not parse PAN details.")
                
                if details.pan_card_number:
                    details.pan_card_number = details.pan_card_number.upper()

                # Validate extracted details
                if (not details.pan_card_number or
                    not details.pan_card_holders_name or
                    not details.date_of_birth or
                    not pan_tools.validate_pan_format(details.pan_card_number)):
                    raise ValueError("Parsed details incomplete or invalid.")

                # Update state to include parsed PAN details
                new_pan_details = details.model_dump()
                return {
                    "pan_details": new_pan_details,
                    "decision": "proceed",
                    "last_executed_node": "collect_manual_details"
                }

            else:
                CORRECTION_SYSTEM_PROMPT = f"""
You are an expert at extracting PAN card information from user input.
Extract the following details from the user's message:

- PAN card number
- Full name of the cardholder
- Date of birth

Current PAN card details as entered by the user for the first time before correction:
{state["pan_details"]}

IMPORTANT:
The user will enter only the details that are incorrect. Do not make any assumptions. 
You have to assume the details are correct from the current PAN card details as entered by the user for the first time before correction.
Fill those existing details in the new PAN card details and then rewrite the incorrect ones.

NOTE: YOU HAVE TO RETURN THE COMPLETE NEW PAN CARD DETAILS AFTER CORRECTION. WHILE THE EXISTING DETAILS ARE UNALTERED.
"""
                details: ParsedPANDetailsState = self.llm_client._get_structured_response(
                    human_prompt=state["user_message"],
                    parser=ParsedPANDetailsState,
                    sys_prompt=CORRECTION_SYSTEM_PROMPT
                )

                print(details)

                if not details:
                    raise ValueError("Could not parse PAN details.")
                
                if details.pan_card_number:
                    details.pan_card_number = details.pan_card_number.upper()

                # Validate extracted details
                if (not details.pan_card_number or
                    not details.pan_card_holders_name or
                    not details.date_of_birth or
                    not pan_tools.validate_pan_format(details.pan_card_number)):
                    raise ValueError("Parsed details incomplete or invalid.")

                # Update state to include parsed PAN details
                new_pan_details = details.model_dump()
                return {
                    "pan_details": new_pan_details,
                    "decision": "proceed",
                    "last_executed_node": "collect_manual_details"
                }

        except Exception as e:
            # Log parsing error for debugging
            print(f"PAN details parsing failed: {e}")

            # Increase retry count and clear details to force retry path
            retries = state.get("retries", 0) + 1
            return {
                "pan_details": {},
                "retries": retries,
                "decision": "retry",
                "last_executed_node": "collect_manual_details"
            }

    @traceable
    def _validate_pan_input(self, state: PanGraphState) -> PanGraphState:
        if state["last_executed_node"] == "collect_manual_details":
            pan_number = state["pan_details"]["pan_card_number"].strip().upper()
# -------------------------------------------------------------------------------------
# FOR PAN PREFILLED OPTION
# -------------------------------------------------------------------------------------
        else:
            pan_number = state["user_message"].strip().upper()
        
        if not pan_tools.validate_pan_format(pan_number):
            return {
                "decision": "retry",
                "retries": state.get("retries", 0) + 1
            }
        
        if state.get("aadhaar_details"):
            pan_details = {
                "pan_card_number": pan_number,
                "date_of_birth": state["aadhaar_details"]["date_of_birth"],
                "pan_card_holders_name": state["aadhaar_details"]["name"]
            }
            return {
                "decision": "proceed",
                "pan_details": pan_details,
                "last_executed_node": "validate_pan_input"
            }
        return {
            "decision": "proceed",
            "last_executed_node": "validate_pan_input"
        }

    def _prompt_for_confirmation(self, state: PanGraphState) -> PanGraphState:
        message = PAN_CONFIRMATION_PROMPT.format(
            pan=state['pan_details']['pan_card_number'],
            name=state['pan_details']['pan_card_holders_name'],
            dob=state['pan_details']['date_of_birth']
        )
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }
    
    @traceable
    def _prepare_for_manual_correction(self, state: PanGraphState) -> PanGraphState:
        # This node clears details and sets the decision for the next prompt.
        self.correction = True
        return {
            "pan_details": state["pan_details"],
            "decision": "correction",
            "last_executed_node": "prepare_for_manual_correction"
        }
    
    def _decide_after_confirmation(self, state: PanGraphState) -> Literal["proceed", "correction"]:
        return "proceed" if "yes" in state["user_message"].lower() else "correction"

    @traceable
    def _verify_with_nsdl(self, state: PanGraphState) -> PanGraphState:
        self.nsdl_verification_count += 1

        nsdl_result = pan_tools.verify_pan_in_nsdl(state["pan_details"])
        is_match = not state.get("aadhaar_details") or (
            nsdl_result.status == "success" and
            pan_tools.compare_pan_and_aadhaar_data(state["pan_details"], state["aadhaar_details"])
        )
        
        decision = "success" if nsdl_result.status == "success" and self.nsdl_verification_count < 3 and is_match else "failure"
        
        return {
            "decision": decision,
            "last_executed_node": "verify_with_nsdl"
        }
    
    # NEW IMAGE PROCESSING METHODS (similar to DL agent)
    @traceable
    def _accept_pan_image(self, state: PanGraphState) -> PanGraphState:
        if self.full_workflow_retry != 0:
            return {
                "response_to_user": "Your PAN card details could not be verified. No worries, please re-upload your PAN card image.\nPlease make sure it is clear and legible.",
                "last_executed_node": "accept_pan_image",
                "pan_details": {}
            }
        else:
            return {
                "response_to_user": "Your PAN card details could not be verified. No worries, You can give another shot. Please upload your PAN card image.",
                "last_executed_node": "accept_pan_image",
                "pan_details": {}
            }
    
    @traceable
    def _pan_ocr_extract(self, state: PanGraphState) -> PanGraphState:
        if self.nsdl_verification_count < 3:
            print("Processing PAN card image...")
            self.full_workflow_retry += 1
            
            time.sleep(2.0)  # Simulate processing time
            
            # Mock OCR response instead of real API call (similar to existing method)
            mock_details = {
                "pan_card_number": "ABCDE1234F",
                "date_of_birth": "01/01/1990",
                "pan_card_holders_name": "Ananya Sharma"
            }

            return {
                "response_to_user": "PAN card image processed successfully. Let me verify these details.",
                "last_executed_node": "pan_ocr_extract",
                "pan_details": mock_details,
                "decision": "proceed"
            }
        else:
            return {
                "response_to_user": PAN_VERIFICATION_FAILED,
                "last_executed_node": "pan_ocr_extract",
                "decision": "terminate"
            }

    @traceable
    def _display_pan_details(self, state: PanGraphState) -> PanGraphState:
        message = f"""Here are the details extracted from your PAN card:

**PAN Number:** {state["pan_details"]["pan_card_number"]}
**Name:** {state["pan_details"]["pan_card_holders_name"]}
**Date of Birth:** {state["pan_details"]["date_of_birth"]}

Are these details correct? (YES/NO)
"""
        return {
            "response_to_user": message,
            "last_executed_node": "display_pan_details",
            "pan_details": state["pan_details"]
        }

    @traceable
    def _acknowledge_pan_details(self, state: PanGraphState) -> PanGraphState:
        if "yes" in state["user_message"].lower():
            return {"decision": "proceed", "pan_details": state["pan_details"]}
        elif "no" in state["user_message"].lower() and self.full_workflow_retry < 2:
            return {"decision": "retry", "pan_details": state["pan_details"]}
        else:
            return {"decision": "terminate", "pan_details": state["pan_details"]}
       
    def _handle_invalid_pan_format(self, state: PanGraphState) -> PanGraphState:
        retries = state.get("retries", 0) + 1
        decision = "terminate" if retries >= 2 else "retry"
        return {
            "retries": retries,
            "decision": decision,
            "last_executed_node": "handle_invalid_pan_format"
        }
    
    @traceable
    def _finish_pan_process(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_VERIFICATION_SUCCESS,
            "status": "SUCCESS",
            "last_executed_node": "finish_pan_process"
        }

    def _terminate_workflow(self, state: PanGraphState) -> PanGraphState:
        return {
            "response_to_user": PAN_TERMINATION,
            "status": "FAILURE",
            "last_executed_node": "terminate_workflow"
        }
    
    def _suggest_next_steps(self, state: OverallState) -> str:
        completed: Set[str] = set(state.get("completed_workflows", []))
        if "pan" not in completed:
             completed.add("pan")
        remaining_docs = self.all_workflows - completed

        if not remaining_docs:
            return "You have now completed all required document verifications!"
        
        remaining_docs = list(remaining_docs)
        remaining_docs.sort()
        next_doc = list(remaining_docs)[0].upper()

        if "FORM60" in next_doc:
            return "You have now completed all required document verifications!"
        else:
            return f"Would you like to proceed with your {next_doc} verification now?"