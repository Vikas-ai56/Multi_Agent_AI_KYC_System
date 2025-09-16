# THE RAG SYSTEM IS NOT YET IMPLEMENTED
# Use CONTEXTUAL_RAG for this

# Temporarily it is just LLM call

from agent.base_agent import BaseSpecialistAgent
from state import OverallState
from llm import LLMFactory 

class GeneralQueryAgent(BaseSpecialistAgent):
    """
    A specialist agent designed to answer general questions about insurance.
    It does not use a RAG pipeline and relies on the LLM's internal knowledge.
    It includes a guardrail to ensure it only responds to insurance-related queries.
    """
    def __init__(self):
        self.llm_client = LLMFactory()
        self.off_topic_response = (
            "I apologize, but my expertise is limited to insurance-related topics. "
            "I can't help with that question. We can continue with your verification process whenever you're ready."
        )

    async def _is_insurance_related(self, user_question: str) -> bool:
        """
        Uses a classification prompt to determine if a question is about insurance.
        This acts as a guardrail for the agent.
        """
        system_prompt = (
            "You are a topic classification model. Your sole task is to determine if the user's "
            "question is related to insurance, policies, claims, premiums, or any associated financial concepts. "
            "Respond with only the word 'INSURANCE' if it is related, and 'OTHER' if it is not."
        )
        
        try:
            response = self.llm_client._get_normal_response(user_question, sys_prompt=system_prompt)
            return "INSURANCE" in response.strip().upper()
        except Exception as e:
            # If the classification fails for any reason, default to being safe and not answering.
            print(f"Error during query classification: {e}")
            return False

    async def handle_step(self, state: OverallState, user_message: str):
        """
        Public method to handle an incoming general query.
        
        It first classifies the query's topic and then either answers it or politely declines.
        """
        if not await self._is_insurance_related(user_message):
            return state, self.off_topic_response
            
        # If the query is on-topic, use a more detailed persona for the answer.
        system_prompt = (
            "You are a helpful and knowledgeable insurance assistant for TATA AIA. Your name is RIA."
            "Your purpose is to answer general questions about insurance concepts clearly and simply. "
            "Your tone should be formal, professional, and empathetic."
            "\n\n**CRITICAL INSTRUCTIONS:**\n"
            "1.  **DO NOT** provide financial advice. Do not suggest specific products, coverage amounts, or investments."
            "2.  **DO NOT** invent or quote any specific numbers like prices, premiums, or policy details. "
            "    You can explain what a 'deductible' is, but you cannot state what a typical deductible is."
            "3.  If you do not know the answer to a question, you must state that you cannot provide that information."
            "4.  Always refer to TATA AIA in the third person (e.g., 'TATA AIA offers policies...')."
            "5.  Keep your answers concise and easy to understand for someone new to insurance."
        )
        
        try:
            response =  self.llm_client._get_normal_response(user_message, sys_prompt=system_prompt)
            return state, response
        except Exception as e:
            print(f"Error during query answering: {e}")
            error_message = "I'm sorry, I encountered an issue while trying to process your question. Please try again later."
            return state, error_message