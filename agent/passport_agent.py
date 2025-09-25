import datetime
from typing import Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver # Use a persistent checkpointer in production
from langgraph.types import Command, Interrupt
from langsmith import traceable
import time

# Assuming these are in the correct paths
from agent.base_agent import BaseSpecialistAgent
from state import OverallState, PassportGraphState, PassportDetailsState
from llm import LLMFactory

class PassportAgent(BaseSpecialistAgent):
    """
    A specialist agent for passport verification.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"passport","pan"}
        self.llm_client = LLMFactory()
        self.full_workflow_retry = 0

        builder = StateGraph(PassportGraphState)

        builder.add_node("accept_passport_image", self._accept_passport_image)
        builder.add_node("spoof_passport_ocr", self._spoof_passport_ocr)
        builder.add_node("display_passport_details", self._display_passport_details)
        builder.add_node("acknowledge", self._acknowledge)
        builder.add_node("finish_passport_process", self._finish_passport_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)
        
        builder.add_edge(START, "accept_passport_image")
        builder.add_edge("accept_passport_image", "spoof_passport_ocr")

        builder.add_conditional_edges(
            "spoof_passport_ocr", 
            lambda s: s.get("decision"), 
            {"proceed": "display_passport_details", "terminate": "terminate_workflow"}
        )

        builder.add_edge("display_passport_details", "acknowledge")

        builder.add_conditional_edges(
            "acknowledge",
            lambda s: s.get("decision"),
            {"retry": "accept_passport_image", "proceed": "finish_passport_process", "terminate": "terminate_workflow"}
        )

        builder.add_edge("finish_passport_process", END)
        builder.add_edge("terminate_workflow", END)

        checkpointer = InMemorySaver()
        interrupt_after = ["accept_passport_image", "display_passport_details"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )

    async def handle_step(self, state: OverallState, user_message: str):
        """
        Handles the current step of its specific workflow.  
        """
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
                "retries": state.get("passport_retries", 0),
                "passport_details": state.get("passport_data", {}),
                "last_executed_node": state.get("last_executed_node",""),
                "status":"IN_PROGRESS",
                "decision": None,
            }
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        state["passport_details"] = final_graph_state.get("passport_details", {})
        last_node = final_graph_state.get("last_executed_node")

        if last_node == "accept_passport_image":
            state["kyc_step"] = "awaiting_passport_image"
        elif last_node == "display_passport_details":
            state["kyc_step"] = "awaiting_passport_details_acknowledgement"
        
        if final_graph_state.get("status") in ["SUCCESS", "FAILURE"]:
            if "passport" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["passport"]
            
            # next_step = self._suggest_next_steps(state)
            # final_graph_state["response_to_user"] += "\n" + next_step
            
            state["active_workflow"] = None
            state["kyc_step"] = None

            if final_graph_state.get("status") == "SUCCESS":
                state["completed_workflows"] = state.get("completed_workflows", []) + ["dl", "aadhaar"]
                next_step = self._suggest_next_steps(state)
                final_graph_state["response_to_user"] += "\n" + next_step
            
                passport_details = final_graph_state["passport_details"]
                state["passport_details"] = PassportDetailsState(
                    name=passport_details["name"],
                    dob=passport_details["dob"],
                    address=passport_details["address"]
                )

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    def _accept_passport_image(self, state: PassportGraphState) -> PassportGraphState:
        if self.full_workflow_retry == 0:
            return {
                "response_to_user": "Please upload your Passport image.",
                "last_executed_node": "accept_passport_image"
            }
        else:
            return {
                "response_to_user": "No Worries, Please re-upload your Passport Image\nPlease make sure it is clear and legible.",
                "last_executed_node": "accept_passport_image",
                "passport_details": {}
            }

# ------------------------------------------------------------------------------------------------- 
# For now OCR is always successful
# ------------------------------------------------------------------------------------------------- 

    def _spoof_passport_ocr(self, state: PassportGraphState) -> PassportGraphState:
        
        print("Verifying your passport details...")
        self.full_workflow_retry += 1

        time.sleep(2.0)

        passport_details = {
            "name": "Ananya Sharma",
            "dob": "01/01/1990",
            "address": "12A, MG Road, Near Central Park, Connaught Place, New Delhi, New Delhi, New Delhi, Delhi, 110001"
        }

        return {
            "decision": "proceed",
            "last_executed_node": "spoof_passport_ocr",
            "passport_details": passport_details,
        }

    def _display_passport_details(self, state: PassportGraphState) -> PassportGraphState:
        message = f"""Here are the details of your Passport.
Name: {state["passport_details"]["name"]}
DOB: {state["passport_details"]["dob"]}
Address: {state["passport_details"]["address"]}

Are these details correct? (YES/NO)
"""
        return {
            "response_to_user": message,
            "last_executed_node": "display_passport_details",
            "passport_details": state["passport_details"],
        }
    
    def _acknowledge(self, state: PassportGraphState) -> PassportGraphState:
        if "yes" in state["user_message"].lower():
            return{"decision": "proceed", "passport_details": state["passport_details"]}
        elif "no" in state["user_message"].lower() and self.full_workflow_retry < 2:
            return{"decision": "retry", "passport_details": state["passport_details"]}
        else:
            return{"decision": "terminate", "passport_details": state["passport_details"]}

    def _finish_passport_process(self, state: PassportGraphState) -> PassportGraphState:
        return {
            "response_to_user": "Thank you for providing the details. We shall verify your details later.",
            "last_executed_node": "finish_passport_process",
            "status": "SUCCESS"
        }

    def _terminate_workflow(self, state: PassportGraphState) -> PassportGraphState:
        return {
            "status": "FAILURE",
            "last_executed_node": "terminate_workflow",
            "response_to_user": "I'm sorry, I'm having trouble understanding the passport details. We'll have to stop the passport process for now. Please start over."
        }

    def _suggest_next_steps(self, state: OverallState) -> str:
        completed: Set[str] = set(state.get("completed_workflows", []))
        # This check is now done in handle_step, but we keep it here for robustness
        if "aadhaar" not in completed:
             completed.add("aadhaar")
        remaining_docs = self.all_workflows - completed

        if "pan" in remaining_docs:
            return f"If you have a PAN card we can proceed with your PAN verification now?\nDo you have one?"
        
        if not remaining_docs:
            return "You have now completed all required document verifications!"
            
        remaining_docs = list(remaining_docs)
        remaining_docs.sort()
        next_doc = list(remaining_docs)[0].upper()
        
        if "FORM60" in next_doc:
            return "You have now completed all required document verifications!"
            
        