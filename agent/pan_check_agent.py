import datetime
from typing import Literal, Set, Tuple

from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Interrupt
from langsmith import traceable

from agent.base_agent import BaseSpecialistAgent
from state import OverallState, PanCheckGraphState
from llm import LLMFactory
from prompts.orchestrate import FORM60_ROUTE_PROMPT 

class Form60Analysis(BaseModel):
    analysis: str
    decision: Literal["yes", "no"]

ANALYSIS_PROMPT = """
You are a KYC compliance expert analyzing whether a person likely has a PAN card based on 
their responses.

USER INTERACTION
{qa_map}

Provide a detailed analysis in the following format:

ANALYSIS:THIS SHOULD BE IN MARKDOWN FORMAT [Write a comprehensive paragraph (4-5 sentences) analyzing the user's situation 
based on Indian tax laws, PAN requirements, and their specific responses. Consider their bank account status, 
ITR filing history, and occupation. Explain why they likely do or don't have a PAN card based on these factors.]

DECISION: [Respond with ONLY "YES" if they likely have PAN, or "NO" if they likely don't have PAN.]

Make your analysis thorough and consider all relevant factors including Indian tax regulations, PAN 
mandatory requirements, and the user's specific circumstances.

YOUR RESPONSE MUST BE EITHER 'yes' OR 'no'
"""

class PanCheckAgent(BaseSpecialistAgent):
    """
    Agent responsible for conducting PAN probe questionnaire when user declares they don't have PAN.
    After collecting answers, it analyzes responses to determine if user should proceed with PAN or Form60.
    """
    
    def __init__(self):
        self.llm_client = LLMFactory()
        warning = "### ⚠ IMPORTANT WARNING\n\nPlease provide accurate information. False information may result in legal action."
        occupations = "Salaried | Self-Employed | Business Owner | Student | Homemaker | Retired | Unemployed | Govt Employee | Freelancer"
        
        # Define the three probe questions
        self.probe_questions = [
            f"{warning}\n\n*Do you currently have an active bank account?*",
            f"{warning}\n\n*Have you filed an Income Tax Return (ITR) in India in the last 3 years?*",
            f"{warning}\n\n*What best describes your occupation?\n\nCHOICES:* {occupations}"
        ]
        
        # Build the state graph
        builder = StateGraph(PanCheckGraphState)
        
        # Add nodes
        builder.add_node("initialize_probe", self._initialize_probe)
        builder.add_node("ask_question", self._ask_question)
        builder.add_node("collect_answer", self._collect_answer)
        builder.add_node("analyze_responses", self._analyze_responses)
        builder.add_node("finish_probe", self._finish_probe)
        
        # Define edges
        builder.add_edge(START, "initialize_probe")
        builder.add_edge("initialize_probe", "ask_question")
        
        # Conditional edge from ask_question to collect_answer (only if there are more questions)
        builder.add_conditional_edges(
            "ask_question",
            lambda s: "collect" if s.get("current_question_index", 0) < len(self.probe_questions) else "analyze",
            {
                "collect": "collect_answer",
                "analyze": "analyze_responses"
            }
        )
        
        # Conditional edge to determine if more questions or analysis
        builder.add_conditional_edges(
            "collect_answer",
            lambda s: "ask" if s.get("current_question_index", 0) < len(self.probe_questions) else "analyze",
            {
                "ask": "ask_question",
                "analyze": "analyze_responses"
            }
        )
        
        builder.add_edge("analyze_responses", "finish_probe")
        builder.add_edge("finish_probe", END)
        
        # Compile graph with checkpointer and interrupts
        checkpointer = InMemorySaver()
        interrupt_after = ["ask_question"]  # Pause after each question
        
        self.graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_after=interrupt_after
        )
    
    @traceable(name="PAN_CHECK_AGENT_HANDLE_STEP")
    async def handle_step(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        """Handle step in the PAN check workflow"""
        config = {"configurable": {"thread_id": state["session_id"]}}
        checkpoint = self.graph.get_state(config)
        final_graph_state = None
        
        if checkpoint and checkpoint.next:
            # Resume graph after interrupt
            try:
                if user_message:
                    await self.graph.aupdate_state(config=config, values={"user_message": user_message})
                    final_graph_state = await self.graph.ainvoke(None, config=config)
                else:
                    final_graph_state = await self.graph.ainvoke(None, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values
        else:
            # Fresh start
            graph_input = PanCheckGraphState(
                session_id=state["session_id"],
                user_message=user_message,
                pan_probe_questions=self.probe_questions,
                current_question_index=0,
                pan_probe_answers={},
                analysis_result=None,
                last_executed_node="",
                response_to_user="",
                status="IN_PROGRESS"
            )
            
            try:
                final_graph_state = await self.graph.ainvoke(graph_input, config=config)
            except Interrupt:
                checkpoint = self.graph.get_state(config)
                final_graph_state = checkpoint.values
        
        # Update main state based on current node
        last_node = final_graph_state.get("last_executed_node")
        
        if last_node == "ask_question":
            state["kyc_step"] = "awaiting_pan_probe_response"
        elif last_node == "finish_probe":
            # Set next step based on analysis result
            analysis_result = final_graph_state.get("analysis_result")
            if analysis_result == "proceed_with_pan":
                state["kyc_step"] = "awaiting_final_pan_decision" 
                state["active_workflow"] = None  # Will be set when user confirms
            else:
                state["kyc_step"] = None
                state["active_workflow"] = "form60"  # Directly proceed to Form60
        else:
            state["kyc_step"] = None
            state["active_workflow"] = None
        
        # If probe is complete, store results
        if final_graph_state.get("status") in ["SUCCESS", "FAILURE"]:
            state["pan_probe_complete"] = True
            state["active_workflow"] = None if final_graph_state.get("analysis_result") == "proceed_with_pan" else "form60"
        
        return state, final_graph_state.get("response_to_user", "An error occurred during PAN verification check.")
    
    @traceable
    def _initialize_probe(self, state: PanCheckGraphState) -> PanCheckGraphState:
        """Initialize the PAN probe questionnaire"""
        return {
            "response_to_user": "I understand you don't have a PAN card. To ensure we follow the correct procedure, I need to ask you a few questions. This is a mandatory step as per regulatory guidelines.",
            "current_question_index": 0,
            "pan_probe_answers": {},
            "last_executed_node": "initialize_probe"
        }
    
    @traceable
    def _ask_question(self, state: PanCheckGraphState) -> PanCheckGraphState:
        """Ask the current question"""
        current_index = state.get("current_question_index", 0)
        
        if current_index < len(self.probe_questions):
            question = self.probe_questions[current_index]
            return {
                "response_to_user": f"Question {current_index + 1}: {question}",
                "last_executed_node": "ask_question"
            }
        else:
            return {
                "last_executed_node": "ask_question"
            }
    
    @traceable
    def _collect_answer(self, state: PanCheckGraphState) -> PanCheckGraphState:
        """Collect the user's answer to the current question"""
        current_index = state.get("current_question_index", 0)
        user_answer = state.get("user_message", "").strip()
        
        if current_index < len(self.probe_questions):
            question = self.probe_questions[current_index]
            current_answers = state.get("pan_probe_answers", {})
            current_answers[f"question_{current_index + 1}"] = {
                "question": question,
                "answer": user_answer
            }
            
            return {
                "pan_probe_answers": current_answers,
                "current_question_index": current_index + 1,
                "last_executed_node": "collect_answer"
            }
        else:
            return {
                "last_executed_node": "collect_answer"
            }
    
    @traceable
    def _analyze_responses(self, state: PanCheckGraphState) -> PanCheckGraphState:
        """Analyze user responses to determine next course of action"""
        answers = state.get("pan_probe_answers", {})
        interaction = ""
        
        # Extract answers for analysis
        bank_account_answer = answers.get("question_1", {}).get("answer", "").lower()
        itr_answer = answers.get("question_2", {}).get("answer", "").lower()
        occupation_answer = answers.get("question_3", {}).get("answer", "").lower()

        for _, qa in answers.items():
            interaction += f"{qa["question"]}\n" + f"{qa["answer"]}\n\n"

        human_message = "You have to analyse the user's interaction and decide whether he has a PAN or NOT"
        
        response = self.llm_client._get_structured_response(
            sys_prompt=FORM60_ROUTE_PROMPT.format(qa_map = interaction),
            human_prompt=human_message,
            parser=Form60Analysis
        )
        
        # Decision logic: if user has indicators they should have PAN, suggest PAN workflow
        if "yes" in response.decision:
            analysis_result = "proceed_with_pan"
            response_message = (
                "Based on your responses, it appears you may be eligible for a PAN card:\n"
                f"• Bank account: {bank_account_answer}\n"
                f"• Filed ITR: {itr_answer}\n"
                f"• Employment status: {occupation_answer}\n\n"
                f"{response.analysis}\n\n"
                "According to regulations, individuals with bank accounts or those who have filed ITR typically need a PAN card. "
                "\n\nWould you like to proceed with **PAN card verification** instead? If you're certain you don't have one, "
                "we can help you with the application process, or proceed with Form 60."
            )
        else:
            analysis_result = "proceed_with_form60"
            response_message = (
                "Based on your responses, it appears you may be eligible for a PAN card:\n"
                f"• Bank account: {bank_account_answer}\n"
                f"• Filed ITR: {itr_answer}\n"
                f"• Employment status: {occupation_answer}\n\n"
                f"{response.analysis}\n\n"
                "Thank you for answering the questions. Based on your responses, we'll proceed with Form 60 "
                "as it appears you may not require a PAN card for your current situation. type 'OK' to proceed with form60"
            )
        
        return {
            "analysis_result": analysis_result,
            "response_to_user": response_message,
            "last_executed_node": "analyze_responses"
        }
    
    @traceable
    def _finish_probe(self, state: PanCheckGraphState) -> PanCheckGraphState:
        """Finish the PAN probe process"""
        return {
            "status": "SUCCESS",
            "last_executed_node": "finish_probe"
        }
