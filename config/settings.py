from pydantic_settings import BaseSettings
from pydantic import Field, BaseModel
from typing import List, Optional
import os

class Settings(BaseSettings):
    """
    Application settings configuration
    """
    # Application settings
    app_name: str = Field(default="TATA AIA KYC System", env="APP_NAME")
    app_version: str = Field(default="1.0.0", env="APP_VERSION")
    debug: bool = Field(default=False, env="DEBUG")
    
    # Server settings
    host: str = Field(default="127.0.0.1", env="HOST")
    port: int = Field(default=8000, env="PORT")
    
    # CORS settings
    allowed_origins: List[str] = Field(
        default=["*"], 
        env="ALLOWED_ORIGINS"
    )
    
    # --- Fields from .env file ---
    gemini_api_key: Optional[str] = Field(default=None, env="GEMINI_API_KEY")
    gemini_base_url: Optional[str] = Field(default=None, env="GEMINI_BASE_URL")
    document_intelligence_api_key: Optional[str] = Field(default=None, env="DOCUMENT_INTELLIGENCE_API_KEY")
    document_intelligence_endpoint: Optional[str] = Field(default=None, env="DOCUMENT_INTELLIGENCE_ENDPOINT")
    cohere_api_key: Optional[str] = Field(default=None, env="COHERE_API_KEY")
    chroma_token: Optional[str] = Field(default=None, env="CHROMA_TOKEN")
    chroma_tenant: Optional[str] = Field(default=None, env="CHROMA_TENANT")
    chroma_database: Optional[str] = Field(default=None, env="CHROMA_DATABASE")
    langsmith_tracing: Optional[str] = Field(default="false", env="LANGSMITH_TRACING")
    langsmith_endpoint: Optional[str] = Field(default="https://api.smith.langchain.com", env="LANGSMITH_ENDPOINT")
    langsmith_api_key: Optional[str] = Field(default=None, env="LANGSMITH_API_KEY")
    langsmith_project: Optional[str] = Field(default=None, env="LANGSMITH_PROJECT")
    mem0_api_key: Optional[str] = Field(default=None, env="MEM0_API_KEY")
    redis_host: Optional[str] = Field(default=None, env="REDIS_HOST")
    redis_db_name: Optional[str] = Field(default=None, env="REDIS_DB_NAME")
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    
    # Webhook settings
    webhook_secret: str = Field(
        default="your-webhook-secret-change-in-production",
        env="WEBHOOK_SECRET"
    )

    # Logging settings
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        case_sensitive = False
        extra = 'ignore' # Ignore extra fields from .env that are not defined in Settings

# Global settings instance
settings = Settings()

# Validation functions
def validate_settings():
    """Validate critical settings"""
    if settings.require_api_key and not settings.webhook_secret:
        raise ValueError("Webhook secret must be set when API key is required")
    
    if settings.port < 1024 and os.name != 'nt':  # Not Windows
        print("Warning: Port < 1024 may require sudo privileges on Unix systems")
    
    return True

# Environment-specific configurations
class DevelopmentConfig(Settings):
    debug: bool = True
    log_level: str = "DEBUG"
    
class ProductionConfig(Settings):
    debug: bool = False
    log_level: str = "INFO"
    require_api_key: bool = True
    allowed_origins: List[str] = []  # Restrict in production
    
class TestingConfig(Settings):
    debug: bool = True
    database_url: str = "sqlite:///./test_kyc_system.db"
    session_timeout_minutes: int = 5

def get_settings(environment: str = None) -> Settings:
    """Get settings based on environment"""
    env = environment or os.getenv("ENVIRONMENT", "development").lower()
    
    if env == "production":
        return ProductionConfig()
    elif env == "testing":
        return TestingConfig()
    else:
        return DevelopmentConfig()