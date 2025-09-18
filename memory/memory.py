import redis
from mem0 import MemoryClient
from typing_extensions import List, Dict, Any

from config.config import Settings
from llm import LLMFactory
from prompts.prompts import SUMMARIZATION_PROMPT_TEMPLATE

WORKING_MEMORY_TURNS = 6
SUMMARIZATION_THRESHOLD = WORKING_MEMORY_TURNS * 2

class MemoryManager:
    def __init__(
        self, 
        session_id: str = None
    ):
        """
        Memory Client Initialization
        """
        self.settings = Settings()
        self.session_id= session_id
        self.update_L2_memory_threshold = 3 

        self.redis_client = redis.Redis(
            host=self.settings.redisdb.host,
            port=10908,
            decode_responses=True,
            username="default", 
            password=self.settings.redisdb.password,
        )
        
        self.mem0 = MemoryClient(
            api_key=self.settings.mem0.api_key
        )
        
        self.llm_client = LLMFactory()

        self.working_memory_key = f"session:{session_id}:working_memory"
        self.episodic_memory_key = f"session:{session_id}:episodic_memory"
        self.working_memory_turns = WORKING_MEMORY_TURNS

# -------------------------------------------------------------------------------------------------
# PUBLIC FUNCTIONS
# -------------------------------------------------------------------------------------------------
  
    def add_turn(
            self, 
            user_message: str, 
            ai_message: str,
            active_workflow: str
        ):
        """
        The main method to add a conversational turn to all relevant memory layers.
        This is called by the orchestrator after every turn.
        """
        # 1. Update L1 Working Memory (Redis)
        self._add_to_working_memory(user_message, ai_message)

        # 2. Update mem0's memory
        self.mem0.add(
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": ai_message}
            ],
            user_id = self.session_id,
            agent_id=f"{active_workflow}-agent",
            metadata={"category": active_workflow}
        )

        self.update_L2_memory_threshold += 1

        # 3. Check if it's time to trigger our custom L2 summarization
        # the memory will be updated only if 3 new conversation states are added in to the redis queue
        history_length = self.redis_client.llen(self.working_memory_key)
        if history_length >= SUMMARIZATION_THRESHOLD and self.update_L2_memory_threshold >= 3:
            self.update_L2_memory_threshold = 0
            self._trigger_and_update_redis_summary()

    def get_memory_context(self, query: str) -> str:
        """
        Retrieves a comprehensive, formatted memory context from all layers
        to be injected into the main orchestrator's prompt.
        """
        # 1. Get L1 context from Redis
        working_memory = self._get_working_memory()

        # 2. Get L2 context from Redis
        redis_summary = self.redis_client.get(self.episodic_memory_key) or "No summary yet."

        # 3. Get L2/L3 context from mem0
        mem0_memories = self.mem0.search(
            query=query,
            user_id = self.session_id,
        )

        formatted_mem0 = self._format_mem0_results(mem0_memories)

        # 4. Combine all layers into a single string for the prompt
        return (
            f"**Key Facts Summary (L2 - Redis):**\n{redis_summary}\n\n"
            f"**Relevant Memories from mem0 (L2/L3):**\n{formatted_mem0}\n\n"
            f"**Recent Conversation History (L1):**\n{working_memory}"
        )

# -------------------------------------------------------------------------------------------------
# PRIVATE FUNCTIONS
# -------------------------------------------------------------------------------------------------
    
    def _add_to_working_memory(
        self, 
        user_message: str, 
        ai_message: str
    ):
        self.redis_client.lpush(self.working_memory_key, f"AI: {ai_message}")
        self.redis_client.lpush(self.working_memory_key, f"User: {user_message}")
        # Retaining only the last 3 questions and answers
        self.redis_client.ltrim(self.working_memory_key, 0, (self.working_memory_turns * 2) - 1)


    def _get_working_memory(self) -> str:
        """
        Retrieves the last N turns as a single formatted string.
        """
        history = self.redis_client.lrange(self.working_memory_key, 0, -1)
        # Reverse the list to get chronological order (oldest to newest)
        return "\n".join(reversed(history))
    
    def _trigger_and_update_redis_summary(self):
        """
        Uses an LLM to create a new summary from the old one and recent history,
        then updates the Redis L2 key and clears the L1 buffer.
        """
        print(f"--- [Memory] Triggering L2 Redis summarization for session: {self.session_id} ---")
        
        full_history = self._get_working_memory()
        current_summary = self.redis_client.get(self.episodic_memory_key) or ""
        
        prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
            current_summary=current_summary,
            new_lines=full_history
        )
        
        try:
            new_summary = self.llm_client._get_normal_response(prompt)
            self.redis_client.set(self.episodic_memory_key, new_summary)
            
            # CRITICAL: After summarizing, we clear the working memory.
            # This prevents the same information from being processed again and keeps
            # the L1 buffer fresh with only post-summary turns.
            self.redis_client.delete(self.working_memory_key)

        except Exception as e:
            print(f"Error during L2 Redis summarization: {e}")
    
    def _format_mem0_results(
        self, 
        memories: List[Dict[str, Any]]
        ) -> str:
        """
        Formats the list of dicts from mem0 into a clean string.
        """
        if not memories:
            return "No relevant memories found."
        
        formatted_list = [f"- {mem["memory"]}" for mem in memories]
        return "\n".join(formatted_list)