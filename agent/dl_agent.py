import datetime
from typing import Literal, Set
from typing import Tuple

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver # Use a persistent checkpointer in production
from langgraph.types import Command, Interrupt
from langsmith import traceable
import time

# Assuming these are in the correct paths
from agent.base_agent import BaseSpecialistAgent
from state import OverallState, DLGraphState, DLDetailsState
from llm import LLMFactory

class DLAgent(BaseSpecialistAgent):
    """
    A specialist agent for passport verification.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"dl", "pan"}
        self.llm_client = LLMFactory()
        self.full_workflow_retry = 0

        builder = StateGraph(DLGraphState)

        builder.add_node("accept_dl_image", self._accept_dl_image)
        builder.add_node("spoof_dl_ocr", self._spoof_dl_ocr)
        builder.add_node("display_dl_details", self._display_dl_details)
        builder.add_node("acknowledge", self._acknowledge)
        builder.add_node("finish_dl_process", self._finish_dl_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)

        builder.add_edge(START, "accept_dl_image")
        builder.add_edge("accept_dl_image", "spoof_dl_ocr")

        builder.add_conditional_edges(
            "spoof_dl_ocr", 
            lambda s: s.get("decision"), 
            {"proceed": "display_dl_details", "terminate": "terminate_workflow"}
        )

        builder.add_edge("display_dl_details", "acknowledge")

        builder.add_conditional_edges(
            "acknowledge",
            lambda s: s.get("decision"),
            {"retry": "accept_dl_image", "proceed": "finish_dl_process", "terminate": "terminate_workflow"}
        )

        builder.add_edge("finish_dl_process", END)
        builder.add_edge("terminate_workflow", END)

        checkpointer = InMemorySaver()
        interrupt_after = ["accept_dl_image", "display_dl_details"]

        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after = interrupt_after
        )

    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
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
                "retries": state.get("dl_retries", 0),
                "dl_details": state.get("dl_data", {}),
                "last_executed_node": state.get("last_executed_node",""),
                "status":"IN_PROGRESS",
                "decision": None,
            }
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        state["dl_details"] = final_graph_state.get("dl_details", {})
        last_node = final_graph_state.get("last_executed_node")

        if last_node == "accept_dl_image":
            state["kyc_step"] = "awaiting_dl_image"
        elif last_node == "display_dl_details":
            state["kyc_step"] = "awaiting_dl_details_acknowledgement"

        if final_graph_state.get("status") in ["SUCCESS", "FAILURE"]:
            if "dl" not in state.get("completed_workflows", []):
                state["completed_workflows"] = state.get("completed_workflows", []) + ["dl"]
            
            # next_step = self._suggest_next_steps(state)
            # final_graph_state["response_to_user"] += "\n" + next_step
            
            state["active_workflow"] = None
            state["kyc_step"] = None

            if final_graph_state.get("status") == "SUCCESS":
                state["completed_workflows"] = state.get("completed_workflows", []) + ["passport", "aadhaar"]
                next_step = self._suggest_next_steps(state)
                final_graph_state["response_to_user"] += "\n" + next_step
            
                dl_details = final_graph_state["dl_details"]
                state["dl_details"] = DLDetailsState(
                    name=dl_details["name"],
                    dob=dl_details["dob"],
                    address=dl_details["address"]
                )

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    def _accept_dl_image(self, state: DLGraphState) -> DLGraphState:
        if self.full_workflow_retry == 0:
            return {
                "response_to_user": "Please upload your DL image.",
                "last_executed_node": "accept_dl_image"
            }
        else:
            return {
                "response_to_user": "No Worries, Please re-upload your DL Image\nPlease make sure it is clear and legible.",
                "last_executed_node": "accept_dl_image",
                "dl_details": {}
            }

# ------------------------------------------------------------------------------------------------- 
# For now OCR is always successful
# ------------------------------------------------------------------------------------------------- 

    def _spoof_dl_ocr(self, state: DLGraphState) -> DLGraphState:
        print("Verifying your DL details...")
        self.full_workflow_retry += 1

        time.sleep(2.0)

        dl_details = {
            "name": "Ananya Sharma",
            "dob": "01/01/1990",
            "address": "12A, MG Road, Near Central Park, Connaught Place, New Delhi, New Delhi, New Delhi, Delhi, 110001"
        }

        return {
            "decision": "proceed",
            "last_executed_node": "spoof_dl_ocr",
            "dl_details": dl_details,
        }

    def _display_dl_details(self, state: DLGraphState) -> DLGraphState:
        message = f"""Here are the details of your DL.
Name: {state["dl_details"]["name"]}
DOB: {state["dl_details"]["dob"]}
Address: {state["dl_details"]["address"]}

Are these details correct? (YES/NO)
"""
        return {
            "response_to_user": message,
            "last_executed_node": "display_dl_details",
            "dl_details": state["dl_details"]
        }

    def _acknowledge(self, state: DLGraphState) -> DLGraphState:
        if "yes" in state["user_message"].lower():
            return{"decision": "proceed", "dl_details": state["dl_details"] }
        elif "no" in state["user_message"].lower() and self.full_workflow_retry < 2:
            return{"decision": "retry", "dl_details": state["dl_details"]}
        else:
            return{"decision": "terminate", "dl_details": state["dl_details"]}

    def _finish_dl_process(self, state: DLGraphState) -> DLGraphState:
        return {
            "response_to_user": "Thank you for providing the details. We shall verify your details later.",
            "last_executed_node": "finish_dl_process",
            "status": "SUCCESS"
        }

    def _terminate_workflow(self, state: DLGraphState) -> DLGraphState:
        return {
            "status": "FAILURE",
            "last_executed_node": "terminate_workflow",
            "response_to_user": "I'm sorry, I'm having trouble understanding the DL details. We'll have to stop the DL process for now. Please start over."
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
            
        