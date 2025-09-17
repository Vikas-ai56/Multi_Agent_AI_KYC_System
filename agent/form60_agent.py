import datetime
from typing import Tuple, Literal, Set

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Interrupt, Command

from agent.base_agent import BaseSpecialistAgent
from state import OverallState, Form60GraphState, Form60Data

class Form60Agent(BaseSpecialistAgent):
    """
    A specialist agent for collecting Form 60 details when a user does not have a PAN card.
    """
    def __init__(self):
        self.all_workflows: Set[str] = {"aadhaar", "pan", "form60"}
        
        builder = StateGraph(Form60GraphState)

        # Node Definitions
        builder.add_node("prompt_for_agri_income", self._prompt_for_agri_income)
        builder.add_node("validate_and_store_income", self._validate_and_store_income)
        builder.add_node("prompt_for_other_income", self._prompt_for_other_income)
        builder.add_node("handle_invalid_income", self._handle_invalid_income)
        builder.add_node("finish_form60_process", self._finish_form60_process)
        builder.add_node("terminate_workflow", self._terminate_workflow)

        # Edge Definitions
        builder.add_edge(START, "prompt_for_agri_income")
        builder.add_edge("prompt_for_agri_income", "validate_and_store_income")
        
        builder.add_conditional_edges(
            "validate_and_store_income",
            lambda s: s.get("decision"),
            {"proceed_to_other": "prompt_for_other_income", "proceed_to_finish": "finish_form60_process", "retry": "handle_invalid_income"}
        )

        builder.add_edge("prompt_for_other_income", "validate_and_store_income")
        
        builder.add_conditional_edges(
            "handle_invalid_income",
            lambda s: s.get("decision"),
            {"retry_agri": "prompt_for_agri_income", "retry_other": "prompt_for_other_income", "terminate": "terminate_workflow"}
        )

        builder.add_edge("finish_form60_process", END)
        builder.add_edge("terminate_workflow", END)
        
        # Graph Compilation
        checkpointer = MemorySaver()
        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after=["prompt_for_agri_income", "prompt_for_other_income"]
        )

    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None

        # ------------ 1. Resume path ---------------------------------
        if checkpoint and checkpoint.next:
            try:
                # put the new user text into the saved state
                await self.graph.aupdate_state(config=config, values={"user_message": user_message})
                # resume execution instead of starting a fresh run
                final_graph_state = await self.graph.ainvoke(Command(resume=user_message), config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        # ------------ 2. Fresh run path ------------------------------
        else:
            graph_input = {
                "session_id": state["session_id"],
                "user_message": user_message,
                "retries": state.get("form60_retries", 0),
                "form60_data": state.get("Form_60", {}),
                "current_question": "agri",
            }
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values

        # ------------ 3. Persist results back into OverallState ------
        state["Form_60"]        = final_graph_state.get("form60_data", {})
        state["form60_retries"] = final_graph_state.get("retries", 0)

        # workflow finished?
        if final_graph_state.get("status") == "SUCCESS":
            if "form60" not in state.get("completed_workflows", []):
                state["completed_workflows"].append("form60")
            state["active_workflow"] = None
            state["kyc_step"]       = None

        elif final_graph_state.get("status") == "FAILURE":
            state["active_workflow"] = None
            state["kyc_step"]       = None

        # update kyc_step while the flow is still running
        last_node = final_graph_state.get("last_executed_node")
        if last_node == "prompt_for_agri_income":
            state["kyc_step"] = "awaiting_form60_agriculture_income"
        elif last_node == "prompt_for_other_income":
            state["kyc_step"] = "awaiting_form60_other_source_income"

        return state, final_graph_state.get("response_to_user", "An error occurred.")

    # --- Node Methods ---
    def _prompt_for_agri_income(self, state: Form60GraphState) -> Form60GraphState:
        message = "To complete Form 60, I need a few details. First, could you please provide your estimated annual income from agricultural sources? (Enter 0 if not applicable)."
        return {"response_to_user": message, "current_question": "agri", "last_executed_node": "prompt_for_agri_income"}

    def _validate_and_store_income(self, state: Form60GraphState) -> Form60GraphState:
        try:
            income = int(state["user_message"].strip())
            current_question = state["current_question"]
            
            # Create a copy of the form_60_data to modify, avoiding direct state mutation.
            form_data = state.get("form60_data", {}).copy()

            if current_question == "agri":
                form_data["agricultural_income"] = income
                # Return the modified copy.
                return {"decision": "proceed_to_other", "form60_data": form_data}
            else: 
                form_data["other_income"] = income
                # Return the modified copy.
                return {"decision": "proceed_to_finish", "form60_data": form_data}
        
        except (ValueError, TypeError):
            return {"decision": "retry"}

    def _prompt_for_other_income(self, state: Form60GraphState) -> Form60GraphState:
        message = "Thank you. Now, please provide your estimated annual income from all other non-agricultural sources."
        return {"response_to_user": message, "current_question": "other", "last_executed_node": "prompt_for_other_income"}

    def _handle_invalid_income(self, state: Form60GraphState) -> Form60GraphState:
        retries = state.get("retries", 0) + 1
        if retries >= 2:
            return {"decision": "terminate"}
        
        retry_decision = "retry_agri" if state["current_question"] == "agri" else "retry_other"
        return {"retries": retries, "decision": retry_decision}

    def _finish_form60_process(self, state: Form60GraphState) -> Form60GraphState:
        message = "Thank you. Your Form 60 details have been recorded successfully."
        # Suggest next steps would also go here.
        return {"response_to_user": message, "status": "SUCCESS", "last_executed_node": "finish_form60_process"}

    def _terminate_workflow(self, state: Form60GraphState) -> Form60GraphState:
        message = "I'm sorry, I'm having trouble understanding the income details. We'll have to stop the Form 60 process for now."
        return {"response_to_user": message, "status": "FAILURE", "last_executed_node": "terminate_workflow"}