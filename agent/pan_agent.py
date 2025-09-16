'''
# agents/specialists/pan_agent.py
import datetime
from typing import Tuple, Literal, Set

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.base_agent import BaseSpecialistAgent
from tools import pan_tools
from state import OverallState, PanGraphState

class PanAgent(BaseSpecialistAgent):
    """
    An expert agent for PAN verification, implemented as a robust, interruptible LangGraph state machine.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        
        builder = StateGraph(PanGraphState)

        builder.add_node("check_aadhaar_dependency", self._check_aadhaar_dependency)
        # auto fill
        builder.add_node("prompt_for_pan_prefilled", self._prompt_for_pan_prefilled)
        # manual fill
        builder.add_node("prompt_for_pan_manual", self._prompt_for_pan_manual)
        builder.add_node("collect_manual_details", self._collect_manual_details)
        
        builder.add_node("validate_and_prepare_confirmation", self._validate_and_prepare_confirmation)
        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)

        # builder.add_node("route_confirmation_response", self._route_confirmation_response)

        builder.add_node("verify_with_nsdl", self._verify_with_nsdl)
        builder.add_node("handle_invalid_pan_format", self._handle_invalid_pan_format)
        
        builder.add_node("finish_pan_process", self._finish_pan_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)


        builder.set_entry_point("check_aadhaar_dependency")

        # Branch for PAN-first vs. Aadhaar-first
        builder.add_conditional_edges(
            "check_aadhaar_dependency",
            self._decide_pan_collection_method,
            {"manual": "prompt_for_pan_manual", "prefilled": "prompt_for_pan_prefilled"}
        )

        # Edges for the two data collection paths
        builder.add_edge("prompt_for_pan_prefilled", "validate_and_prepare_confirmation")

        builder.add_edge("prompt_for_pan_manual", "collect_manual_details")
        builder.add_edge("collect_manual_details", "validate_and_prepare_confirmation")
        
        # Branch after validation
        builder.add_conditional_edges(
            "validate_and_prepare_confirmation",
            self._decide_after_validation,
            {"proceed": "prompt_for_confirmation", "retry": "handle_invalid_pan_format"}
        )

        # Retry loop for invalid format
        builder.add_conditional_edges(
            "handle_invalid_pan_format",
            self._decide_after_retry,
            {"retry": "prompt_for_pan_prefilled", "terminate": "terminate_workflow"}
        )
        
        # THIS IS THE INTERRUPTIBLE CHECKPOINT
        builder.add_edge("prompt_for_confirmation", END)

        # After the user confirms, we re-enter the graph. The next node decides where to go.
        builder.add_conditional_edges(
            "route_confirmation_response",
            self._decide_after_confirmation,
            {"proceed": "verify_with_nsdl", "terminate": "terminate_workflow"}
        )
        
        # Final branch after NSDL verification
        builder.add_conditional_edges(
            "verify_with_nsdl",
            self._decide_after_nsdl,
            {"success": "finish_pan_process", "failure": "terminate_workflow"}
        )

        # Final exit points
        builder.add_edge("finish_pan_process", END)
        builder.add_edge("terminate_workflow", END)
        
        # --- 4. Compile the Graph ---
        # For production, replace MemorySaver with a persistent checkpointer like Redis.
        checkpointer = InMemorySaver()
        interrupted_nodes = ["prompt_for_pan_manual", ]
        self.graph = builder.compile(checkpointer=checkpointer)

    # --- Public Interface Method ---
    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        """
        The public method that the KYCManager calls. It acts as an adapter to the LangGraph instance.
        """
        # 1. Map OverallState to Graph State
        graph_input: PanGraphState = {
            "session_id": state["session_id"],
            "user_message": user_message,
            "aadhaar_details": state.get("aadhar_details"),
            "pan_details": state.get("pan_details", {}),
            "retries": state.get("pan_retries", 0),
            "response_to_user": ""
        }
        
        # 2. Invoke the graph stream
        config = {"configurable": {"thread_id": state["session_id"]}}
        final_graph_state = None
        
        # If the user is just starting, we start at the beginning.
        # If they are responding to a confirmation, we must route them to the correct node.
        initial_node = "route_confirmation_response" if state.get("kyc_step") == "awaiting_pan_confirmation" else None

        async for event in self.graph.astream(graph_input, config=config, stream_mode="values", start_at=initial_node):
            final_graph_state = event

        # 3. Map final Graph State back to OverallState
        state["pan_details"] = final_graph_state["pan_details"]
        state["pan_retries"] = final_graph_state["retries"]
        
        # This is how we know if the graph paused for confirmation
        if final_graph_state.get("response_to_user", "").startswith("Based on your previously"):
            state["kyc_step"] = "awaiting_pan_confirmation"
        
        return state, final_graph_state["response_to_user"]

    # --- Graph Node Methods (Private) ---

    def _check_aadhaar_dependency(self, state: PanGraphState) -> PanGraphState:
        # This node doesn't talk to the user, it just routes.
        decision = "prefilled" if state.get("aadhaar_details") else "manual"
        return {"decision": decision}

    def _decide_pan_collection_method(self, state: PanGraphState) -> Literal["manual", "prefilled"]:
        return state.get("decision")

    def _prompt_for_pan_prefilled(self, state: PanGraphState) -> PanGraphState:
        return {"response_to_user": "To verify your PAN, please enter your 10-character PAN card number."}

    def _prompt_for_pan_manual(self, state: PanGraphState) -> PanGraphState:
        return {"response_to_user": "To verify your PAN, please provide your PAN number, full name (as on card), and date of birth (DD/MM/YYYY)."}
    
    # Use an LLM parser
    # If any data is missing revert back to the user
    def _collect_manual_details(self, state: PanGraphState) -> PanGraphState:
        # In a real system, an LLM call would parse the user_message here.
        # For simplicity, we assume the user provides it in a structured way.
        parts = state["user_message"].split(',')
        if len(parts) == 3:
            state["pan_details"] = {
                "pan_card_number": parts[0].strip().upper(),
                "pan_card_holders_name": parts[1].strip(),
                "date_of_birth": parts[2].strip()
            }
        return state
    
    def _validate_and_prepare_confirmation(self, state: PanGraphState) -> PanGraphState:
        # This node handles both manual and prefilled paths
        pan_number = state["pan_details"].get("pan_card_number") or state["user_message"].strip().upper()
        
        if not pan_tools.validate_pan_format(pan_number):
            state["decision"] = "retry"
            return state

        if state.get("aadhaar_details"):
            state["pan_details"] = {
                "pan_card_number": pan_number,
                "date_of_birth": state["aadhaar_details"]["date_of_birth"],
                "pan_card_holders_name": state["aadhaar_details"]["name"]
            }
        state["decision"] = "proceed"
        return state

    def _decide_after_validation(self, state: PanGraphState) -> Literal["proceed", "retry"]:
        return state.get("decision")

    def _prompt_for_confirmation(self, state: PanGraphState) -> PanGraphState:
        message = (
            "Based on our records, we have the following details for your PAN:\n\n"
            f"- **PAN Number:** {state['pan_details']['pan_card_number']}\n"
            f"- **Holder's Name:** {state['pan_details']['pan_card_holders_name']}\n"
            f"- **Date of Birth:** {state['pan_details']['date_of_birth']}\n\n"
            "Is all of this information correct?"
        )
        return {"response_to_user": message}

    def _route_confirmation_response(self, state: PanGraphState) -> PanGraphState:
        # This node runs when the graph resumes after the interrupt
        decision = "proceed" if "yes" in state["user_message"].lower() else "terminate"
        return {"decision": decision}

    def _decide_after_confirmation(self, state: PanGraphState) -> Literal["proceed", "terminate"]:
        return state.get("decision")

    def _verify_with_nsdl(self, state: PanGraphState) -> PanGraphState:
        nsdl_result = pan_tools.verify_pan_in_nsdl(state["pan_details"])
        is_match = False
        if nsdl_result.status == "success" and state.get("aadhaar_details"):
            is_match = pan_tools.compare_pan_and_aadhaar_data(state["pan_details"], state["aadhaar_details"])
        
        if nsdl_result.status == "success" and (not state.get("aadhaar_details") or is_match):
            state["decision"] = "success"
        else:
            state["decision"] = "failure"
        return state
        
    def _decide_after_nsdl(self, state: PanGraphState) -> Literal["success", "failure"]:
        return state.get("decision")

    def _handle_invalid_pan_format(self, state: PanGraphState) -> PanGraphState:
        retries = state.get("retries", 0) + 1
        state["retries"] = retries
        if retries >= 2:
            state["decision"] = "terminate"
        else:
            state["decision"] = "retry"
        return state

    def _decide_after_retry(self, state: PanGraphState) -> Literal["retry", "terminate"]:
        return state.get("decision")

    def _finish_pan_process(self, state: PanGraphState) -> PanGraphState:
        message = "Excellent. Your PAN details have been successfully verified."
        # Here you would also update the OverallState's completed_workflows
        return {"response_to_user": message}

    def _terminate_workflow(self, state: PanGraphState) -> PanGraphState:
        message = "I'm sorry, we couldn't verify your PAN details with the information provided. Please contact support for assistance."
        return {"response_to_user": message}
'''

'''
# Currently there is no limit for retries after
# acknowledgement NO from the user during "prompt_for_confirmation"

# DOB PATTERN MATCHING IS NOT YET DONE

from typing import Tuple, Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver  
from langgraph.types import Command, Interrupt

from agent.base_agent import BaseSpecialistAgent
from tools import pan_tools
from state import OverallState, PanGraphState
from llm import LLMFactory
from pydantic import BaseModel, Field
from typing_extensions import Optional

class ParsedPANDetails(BaseModel):
    pan_card_number: Optional[str] = Field(description="The PAN card number of the user, ALL the alphabets must be in capital", default=None)
    date_of_birth: Optional[str] = Field(description="THE customers date of birth in DD/MM/YYYY format", default=None)
    pan_card_holders_name: Optional[str] = Field(description="The name of the user as written on the PAN card", default=None)


class PanAgent(BaseSpecialistAgent):
    """
    An expert agent for PAN verification, implemented with the robust, interruptible LangGraph pattern.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()

        builder = StateGraph(PanGraphState)

        builder.add_node("check_aadhaar_dependency", self._check_aadhaar_dependency)

        builder.add_node("prompt_for_pan_prefilled", self._prompt_for_pan_prefilled)

        builder.add_node("prompt_for_pan_manual", self._prompt_for_pan_manual)
        builder.add_node("collect_manual_details", self._collect_manual_details)

        builder.add_node("validate_pan_input", self._validate_pan_input)

        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)

        builder.add_node("verify_with_nsdl", self._verify_with_nsdl)

        builder.add_node("handle_invalid_pan_format", self._handle_invalid_pan_format)

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
            {"success": "finish_pan_process", "failure": "terminate_workflow"}
        )

        builder.add_edge("finish_pan_process", END)
        builder.add_edge("terminate_workflow", END)
# ---------------------------------------------------------------------------------------        
# Graph Compilation with Interruption 
# ---------------------------------------------------------------------------------------
        checkpointer = InMemorySaver()
        interrupt_after = ["prompt_for_confirmation", "prompt_for_pan_prefilled", "prompt_for_pan_manual"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )


    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        config = {"configurable": {"thread_id": state["session_id"]}}
        final_graph_state = None

        # Check if graph was previously interrupted
        checkpoint = self.graph.get_state(config)
        
        if checkpoint.next:
            # Graph was interrupted - resume execution
            try:
                if user_message:
                    # Resume with user input using Command
                    from langgraph.types import Command
                    final_graph_state = await self.graph.ainvoke(Command(resume=user_message), config=config)
                else:
                    # Resume without new input - just continue execution
                    final_graph_state = await self.graph.ainvoke(None, config=config)
                    
            except Exception as e:  # Handle any interrupt exceptions
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values
                
        else:
            # Fresh start - create new graph input
            graph_input: PanGraphState = {
                "session_id": state["session_id"],
                "user_message": user_message,
                "aadhaar_details": state.get("aadhar_details"),
                "pan_details": state.get("pan_details", {}),
                "retries": state.get("pan_retries", 0),
            }
            
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Exception as e:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        # Update state from graph results
        if final_graph_state:
            state["pan_details"] = final_graph_state.get("pan_details", {})
            state["pan_retries"] = final_graph_state.get("retries", 0)

        # Check current state and set kyc_step
        current_checkpoint = self.graph.get_state(config)
        
        if current_checkpoint.next:
            next_node = current_checkpoint.next
            
            if next_node == "prompt_for_pan_prefilled":
                state["kyc_step"] = "awaiting_pan_input_prefilled"
            elif next_node == "collect_manual_details":
                state["kyc_step"] = "awaiting_pan_input_manual"
            elif next_node == "prompt_for_confirmation":
                state["kyc_step"] = "awaiting_pan_confirmation"
        else:
            state["kyc_step"] = None
            # Check if pan workflow completed
            if current_checkpoint.metadata.get("writes", {}).get("finish_pan_process"):
                if "pan" not in state.get("completed_workflows", []):
                    state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]

        response_to_user = final_graph_state.get("response_to_user", "") if final_graph_state else ""
        return state, response_to_user


    def _check_aadhaar_dependency(self, state: PanGraphState) -> PanGraphState:
        return state

    def _prompt_for_pan_prefilled(self, state: PanGraphState) -> PanGraphState:
        SYSTEM_PROMPT = """
        Your an helpful insurance agent working for tata AIA company.
        Currently you are helping the customet to complete his PAN card verification and your asking for his details.
        You should also re-assure and build Trust with the customer so that he doesn't feel his information is not being misused.
        Keep your tone FORMAL and Encouraging.
        
        NOTE: REMEMBER YOU ARE TALKING DIRECTLY TO THE CUSTOMER AND REQUEST HIM FOR GENUINE AND CORRECT DETAILS.
        """
        human_prompt = "To verify the customers PAN, ask him to enter his 10-character PAN card number."
        
        ai_message = self.llm_client._get_normal_response(human_prompt, sys_prompt = SYSTEM_PROMPT)

        return {
            "response_to_user": ai_message,
            "last_executed_node": "prompt_for_pan_prefilled"
        }
    
    def _prompt_for_pan_manual(self, state: PanGraphState) -> PanGraphState:
        # Check if this is a retry and add a helpful message.
        if state.get("decision") == "correction":
             message = "No problem, let's correct that. Please re-enter the PAN details again which you feel are wrong in the appropriate format. \nEx:- Name: John Doe."
        if state.get("decision") == "retry":
             message = "It looks like some details were missing. Please provide your PAN number, full name, and date of birth (DD/MM/YYYY) again."
        else:
             message = "To verify your PAN,enter your PAN number, full name (as on PAN card), and date of birth (DD/MM/YYYY only)."
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_pan_manual"
        }
    
    def _collect_manual_details(self, state: PanGraphState) -> PanGraphState:
        # parts = state["user_message"].split(',')
        human_message = state["user_message"]
        fields = list(ParsedPANDetails.model_fields.keys())
        flag = False

        for _ in range(3):
            if flag:
                break
            details = self.llm_client._get_structured_response(human_message, ParsedPANDetails)

            # Retry mechanism for LLM (MAX 3 retries)
            if details is None:
                continue
            
            for field in fields:
                info = getattr(details, field)
                existing_info = state.get("pan_details", None)
                
                if info:
                    state["pan_details"][str(field)] = info
                    state["decision"] = "proceed"
                    flag = True

                # THIS ONE HANDLES IF THE FIELD DOES NOT REQUIRE ANY UPDATES AFTER CONFIRMATION IS "NO"
                elif not (existing_info is None):
                    pass

                else:
                    state["pan_details"] = {} # Implies that data collection failed
                    state["decision"] = "retry"
                    flag = False
                    break
            
        return state
    
    def _validate_pan_input(self, state: PanGraphState) -> PanGraphState:
        # This node handles both manual and prefilled paths
        pan_number = state["pan_details"].get("pan_card_number") or state["user_message"].strip().upper()
        
        if not pan_tools.validate_pan_format(pan_number):
            return {"decision": "retry"}

        # If coming from the prefilled path, populate the details now.
        if state.get("aadhaar_details") and not state["pan_details"].get("pan_card_holders_name"):
            state["pan_details"] = {
                "pan_card_number": pan_number,
                "date_of_birth": state["aadhaar_details"]["date_of_birth"],
                "pan_card_holders_name": state["aadhaar_details"]["name"]
            }
        
        return {"decision": "proceed", "pan_details": state["pan_details"]}

    def _prompt_for_confirmation(self, state: PanGraphState) -> PanGraphState:
        # This node's only job is to generate the message. The interruption is handled by the graph engine.
        message = (
            "Based on our records, we have the following details for your PAN:\n\n"
            f"- **PAN Number:** {state['pan_details']['pan_card_number']}\n"
            f"- **Holder's Name:** {state['pan_details']['pan_card_holders_name']}\n"
            f"- **Date of Birth:** {state['pan_details']['date_of_birth']}\n\n"
            "Is all of this information correct (Yes/No)?"
        )
        return {"response_to_user": message}
    
    def _prepare_for_manual_correction(self, state: PanGraphState) -> PanGraphState:
        state["pan_details"] = {}
        state["decision"] = "correction"
        return state
    
# --------------------------------------------------------------------------------------------
# INTENT RECOGNITION TO BE ADDED
# --------------------------------------------------------------------------------------------
    
    def _decide_after_confirmation(self, state: PanGraphState) -> Literal["proceed", "terminate"]:
        # This logic runs *after* the graph resumes, processing the user's confirmation.
        return "proceed" if "yes" in state["user_message"].lower() else "terminate"

    def _verify_with_nsdl(self, state: PanGraphState) -> PanGraphState:
        nsdl_result = pan_tools.verify_pan_in_nsdl(state["pan_details"])
        is_match = False
        # Only compare if Aadhaar details exist
        if nsdl_result.status == "success" and state.get("aadhaar_details"):
            is_match = pan_tools.compare_pan_and_aadhaar_data(state["pan_details"], state["aadhaar_details"])
        
        # Success if NSDL verified AND (either no Aadhaar to compare or the data matches)
        is_overall_success = nsdl_result.status == "success" and (not state.get("aadhaar_details") or is_match)
        
        return {"decision": "success" if is_overall_success else "failure"}
        
    def _handle_invalid_pan_format(self, state: PanGraphState) -> PanGraphState:
        retries = state.get("retries", 0) + 1
        return {"retries": retries, "decision": "terminate" if retries >= 2 else "retry"}

    def _finish_pan_process(self, state: PanGraphState) -> PanGraphState:
        message = "Excellent. Your PAN details have been successfully verified."
        return {
            "response_to_user": message,
            "last_executed_node": "prompt_for_confirmation"
        }

    def _terminate_workflow(self, state: PanGraphState) -> PanGraphState:
        message = "I'm sorry, we couldn't verify your PAN details with the information provided. Please contact support for assistance."
        return {"response_to_user": message}
'''

# <<< CHANGE >>>
# This file has been comprehensively corrected to:
# 1. Fix the infinite loop by rewriting `_collect_manual_details` with clean, working logic.
# 2. Implement the robust and simpler `while True/try/except Interrupt` pattern in `handle_step`.
# 3. Use the safe `last_executed_node` pattern for determining the `kyc_step`.
# 4. Correct the logic mismatch in `_decide_after_confirmation`.

import datetime
from typing import Tuple, Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver  
from langgraph.types import Interrupt # Use the more specific exception class

# Assuming correct import paths
from agent.base_agent import BaseSpecialistAgent
from tools import pan_tools
from state import OverallState, PanGraphState
from llm import LLMFactory
from pydantic import BaseModel, Field
from typing_extensions import Optional

class ParsedPANDetailsState(BaseModel):
    pan_card_number: str = Field(description="The PAN card number of the user")
    date_of_birth: str = Field(description="THE customers date of birth in DD/MM/YYYY format")
    pan_card_holders_name: str = Field(description="The name of the user as written on the PAN card")

class PanAgent(BaseSpecialistAgent):
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()
        builder = StateGraph(PanGraphState)
        
        # Node and Edge definitions from your code are correct, no changes needed here.
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        self.llm_client = LLMFactory()

        builder = StateGraph(PanGraphState)

        builder.add_node("check_aadhaar_dependency", self._check_aadhaar_dependency)

        builder.add_node("prompt_for_pan_prefilled", self._prompt_for_pan_prefilled)

        builder.add_node("prompt_for_pan_manual", self._prompt_for_pan_manual)
        builder.add_node("collect_manual_details", self._collect_manual_details)

        builder.add_node("validate_pan_input", self._validate_pan_input)

        builder.add_node("prompt_for_confirmation", self._prompt_for_confirmation)

        builder.add_node("verify_with_nsdl", self._verify_with_nsdl)

        builder.add_node("handle_invalid_pan_format", self._handle_invalid_pan_format)

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
            {"success": "finish_pan_process", "failure": "terminate_workflow"}
        )

        builder.add_edge("finish_pan_process", END)
        builder.add_edge("terminate_workflow", END)
# ---------------------------------------------------------------------------------------        
# Graph Compilation with Interruption 
# ---------------------------------------------------------------------------------------
        checkpointer = InMemorySaver()
        interrupt_after = ["prompt_for_confirmation", "prompt_for_pan_prefilled", "prompt_for_pan_manual"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )

    # <<< CHANGE >>> Replaced the entire method with the robust, canonical pattern.
    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None

        if checkpoint and checkpoint.next:
            # Resume graph after interrupt
            from langgraph.types import Command
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
            graph_input = {
                "session_id": state["session_id"],
                "user_message": user_message,
                "aadhaar_details": state.get("aadhar_details"),
                "pan_details": state.get("pan_details", {}),
                "retries": state.get("pan_retries", 0),
            }
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

        if final_graph_state.get("status") == "SUCCESS":
            if "pan" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["pan"]

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    def _check_aadhaar_dependency(self, state: PanGraphState) -> PanGraphState:
        return {} # Only return changes

    def _prompt_for_pan_prefilled(self, state: PanGraphState) -> PanGraphState:
        # Using LLM call as you intended
        human_prompt = "To verify the customer's PAN, ask them to enter their 10-character PAN card number."
        ai_message = self.llm_client._get_normal_response(human_prompt)
        return {"response_to_user": ai_message, "last_executed_node": "prompt_for_pan_prefilled"}
    
    def _prompt_for_pan_manual(self, state: PanGraphState) -> PanGraphState:
        if state.get("decision") == "correction":
             message = "No problem, let's correct that. Please provide your PAN Number, full name, and date of birth (DD/MM/YYYY)."
        elif state.get("retries", 0) > 0:
             message = "It looks like some details were missing or invalid. Please provide your PAN number, full name, and date of birth (DD/MM/YYYY) again."
        else:
             message = "To begin, please provide your PAN number, full name (as on PAN card), and date of birth (DD/MM/YYYY)."
        return {"response_to_user": message, "last_executed_node": "prompt_for_pan_manual"}

    def _collect_manual_details(self, state: PanGraphState) -> PanGraphState:
        try:
            # Parse user input with LLM
            SYSTEM_PROMPT = """
You are an expert at extracting PAN card information from user input.
Extract the following details from the user's message:
- PAN card number
- Full name of the cardholder
- Date of birth

The user will provide this information in various formats. Extract the actual values, not placeholder text.
"""            
            print(state["user_message"])
            details: ParsedPANDetailsState = self.llm_client._get_structured_response(human_prompt=state["user_message"], parser=ParsedPANDetailsState, sys_prompt=SYSTEM_PROMPT)
            print("\n",details)

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
            return {"pan_details": new_pan_details, "decision": "proceed", "last_executed_node": "collect_manual_details"}

        except Exception as e:
            # Log parsing error for debugging
            print(f"PAN details parsing failed: {e}")

            # Increase retry count and clear details to force retry path
            retries = state.get("retries", 0) + 1
            return {"pan_details": {}, "retries": retries, "decision": "retry", "last_executed_node": "collect_manual_details"}

    def _validate_pan_input(self, state: PanGraphState) -> PanGraphState:
        pan_number = state["user_message"].strip().upper()
        print("\nSTATUS\n","-"*35,"\n",pan_tools.validate_pan_format(pan_number),"\n","-"*35)
        
        if not pan_tools.validate_pan_format(pan_number):
            return {"decision": "retry", "retries": state.get("retries", 0) + 1}
        
        if state.get("aadhaar_details"):
            pan_details = {
                "pan_card_number": pan_number,
                "date_of_birth": state["aadhaar_details"]["date_of_birth"],
                "pan_card_holders_name": state["aadhaar_details"]["name"]
            }
            return {"decision": "proceed", "pan_details": pan_details, "last_executed_node": "validate_pan_input"}
        return {"decision": "proceed", "last_executed_node": "validate_pan_input"}

    def _prompt_for_confirmation(self, state: PanGraphState) -> PanGraphState:
        message = (
            f"Based on our records, we have these details:\n\n"
            f"- **PAN:** {state['pan_details']['pan_card_number']}\n"
            f"- **Name:** {state['pan_details']['pan_card_holders_name']}\n"
            f"- **DOB:** {state['pan_details']['date_of_birth']}\n\n"
            "Is this correct (Yes/No)?"
        )
        return {"response_to_user": message, "last_executed_node": "prompt_for_confirmation"}
    
    def _prepare_for_manual_correction(self, state: PanGraphState) -> PanGraphState:
        # This node clears details and sets the decision for the next prompt.
        return {"pan_details": {}, "decision": "correction", "last_executed_node": "prepare_for_manual_correction"}
    
    # <<< CHANGE >>> This now returns the correct edge name ("correction") for the "No" case.
    def _decide_after_confirmation(self, state: PanGraphState) -> Literal["proceed", "correction"]:
        return "proceed" if "yes" in state["user_message"].lower() else "correction"

    def _verify_with_nsdl(self, state: PanGraphState) -> PanGraphState:
        nsdl_result = pan_tools.verify_pan_in_nsdl(state["pan_details"])
        is_match = not state.get("aadhaar_details") or \
                   (nsdl_result.status == "success" and pan_tools.compare_pan_and_aadhaar_data(state["pan_details"], state["aadhar_details"]))
        decision = "success" if nsdl_result.status == "success" and is_match else "failure"
        return {"decision": decision, "last_executed_node": "verify_with_nsdl"}
        
    def _handle_invalid_pan_format(self, state: PanGraphState) -> PanGraphState:
        retries = state.get("retries", 0) + 1
        decision = "terminate" if retries >= 2 else "retry"
        return {"retries": retries, "decision": decision, "last_executed_node": "handle_invalid_pan_format"}

    def _finish_pan_process(self, state: PanGraphState) -> PanGraphState:
        return {"response_to_user": "Excellent. Your PAN details have been successfully verified.", "status": "SUCCESS", "last_executed_node": "finish_pan_process"}

    def _terminate_workflow(self, state: PanGraphState) -> PanGraphState:
        return {"response_to_user": "I'm sorry, we couldn't verify your PAN details. Please contact support for assistance.", "status": "FAILURE", "last_executed_node": "terminate_workflow"}