from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv
import os
from typing import List

load_dotenv()

class DocumentIntelligenceSettings(BaseSettings):
    api_key: str = os.getenv("DOCUMENT_INTELLIGENCE_API_KEY")
    endpoint: str = os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT")

class LLMSettings(BaseSettings):
    api_key: str = os.getenv("GEMINI_API_KEY")
    base_url: str = os.getenv("GEMINI_BASE_URL")

class CohereSettings(BaseSettings):
    api_key: str = os.getenv("COHERE_API_KEY")
    base_url: str = "https://api.cohere.ai/v2"
    client_name: str = "Development_Phase"
    timeout: float = 4.0

class ChromaDbSettings(BaseSettings):
    tenant: str = os.getenv("CHROMA_TENANT")
    database: str = os.getenv("CHROMA_DATABASE")
    token: str = os.getenv("CHROMA_TOKEN")

class Mem0Settings(BaseSettings):
    api_key: str = os.getenv("MEM0_API_KEY")

class RedisDbSettings(BaseSettings):
    host: str = os.getenv("REDIS_HOST")
    password: str = os.getenv("REDIS_PASSWORD")
    db_name: str = os.getenv("REDIS_DB_NAME")

class LangSmithSettings(BaseSettings):
    tracing: str = os.getenv("LANGSMITH_TRACING", "false")
    endpoint: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    api_key: str = os.getenv("LANGSMITH_API_KEY")
    project: str = os.getenv("LANGSMITH_PROJECT")

class Settings(BaseSettings):
    # FastAPI specific settings
    app_name: str = "TATA AIA KYC System"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS settings
    allowed_origins: List[str] = ["*"]
    
    # Webhook settings
    webhook_secret: str = "your-webhook-secret"
    
    # External service configurations
    document_intelligence: DocumentIntelligenceSettings = DocumentIntelligenceSettings()
    llm: LLMSettings = LLMSettings()
    cohere: CohereSettings = CohereSettings()
    chromadb: ChromaDbSettings = ChromaDbSettings()
    redisdb: RedisDbSettings = RedisDbSettings()
    mem0: Mem0Settings = Mem0Settings()
    langsmith: LangSmithSettings = LangSmithSettings()
    
    # Direct environment variables for backward compatibility
    gemini_api_key: str = os.getenv("GEMINI_API_KEY")
    gemini_base_url: str = os.getenv("GEMINI_BASE_URL")
    document_intelligence_api_key: str = os.getenv("DOCUMENT_INTELLIGENCE_API_KEY")
    document_intelligence_endpoint: str = os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT")
    cohere_api_key: str = os.getenv("COHERE_API_KEY")
    chroma_token: str = os.getenv("CHROMA_TOKEN")
    chroma_tenant: str = os.getenv("CHROMA_TENANT")
    chroma_database: str = os.getenv("CHROMA_DATABASE")
    langsmith_tracing: str = os.getenv("LANGSMITH_TRACING", "false")
    langsmith_endpoint: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    langsmith_api_key: str = os.getenv("LANGSMITH_API_KEY")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT")
    mem0_api_key: str = os.getenv("MEM0_API_KEY")
    redis_host: str = os.getenv("REDIS_HOST")
    redis_db_name: str = os.getenv("REDIS_DB_NAME")
    redis_password: str = os.getenv("REDIS_PASSWORD")

    class Config:
        env_file = ".env"
        extra = "allow"  # Allow extra fields from environment

@lru_cache
def get_settings():
    return Settings()

# Create global settings instance
settings = Settings()