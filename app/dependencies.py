from fastapi import Header, HTTPException, Query, Depends
from typing import Optional, Dict, Any
import re
import logging

logger = logging.getLogger(__name__)

async def get_api_key(x_api_key: Optional[str] = Header(None)):
    """
    Validate API key for authentication
    In production, implement proper API key validation
    """
    # For development, this is optional
    # In production, validate against your authentication system
    if x_api_key:
        # Add your API key validation logic here
        # Example: check against database of valid API keys
        pass
    
    return x_api_key

async def validate_session_id(session_id: str) -> str:
    """
    Validate session ID format and basic requirements
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID is required")
    
    if len(session_id) < 10:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    # Validate session ID pattern (api-session-uuid or cli-session-uuid)
    session_pattern = r'^(api|cli)-session-[a-f0-9\-]{36}$'
    if not re.match(session_pattern, session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    return session_id

async def get_current_session(session_id: str = Depends(validate_session_id)) -> str:
    """
    Get current session with validation
    """
    return session_id

async def validate_webhook_secret(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Validate webhook secret for webhook endpoints
    """
    # In production, validate webhook signatures
    # Example: HMAC validation with shared secret
    if x_webhook_secret:
        # Add your webhook secret validation logic here
        pass
    
    return x_webhook_secret

async def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size")
) -> Dict[str, int]:
    """
    Get pagination parameters for list endpoints
    """
    return {
        "page": page,
        "size": size,
        "offset": (page - 1) * size,
        "limit": size
    }

async def validate_user_permissions(
    user_id: Optional[str] = Header(None, alias="X-User-ID"),
    api_key: Optional[str] = Depends(get_api_key)
):
    """
    Validate user permissions for protected endpoints
    """
    # In production, implement proper authorization
    # Check user permissions, roles, etc.
    
    return {
        "user_id": user_id,
        "api_key": api_key,
        "is_authenticated": bool(api_key or user_id)
    }

class RateLimiter:
    """
    Simple rate limiter implementation
    In production, use Redis-based rate limiting
    """
    def __init__(self):
        self.requests = {}
    
    async def check_rate_limit(
        self, 
        client_id: str, 
        max_requests: int = 100, 
        window_seconds: int = 60
    ):
        # Implement rate limiting logic
        # This is a simplified version
        return True

rate_limiter = RateLimiter()

async def apply_rate_limit(
    client_ip: str = Header(None, alias="X-Forwarded-For")
):
    """
    Apply rate limiting to endpoints
    """
    if not client_ip:
        client_ip = "unknown"
    
    # Check rate limit
    allowed = await rate_limiter.check_rate_limit(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded"
        )
    
    return client_ip

async def log_request(
    user_agent: Optional[str] = Header(None, alias="User-Agent"),
    client_ip: str = Header(None, alias="X-Forwarded-For")
):
    """
    Log request details for monitoring
    """
    logger.info(f"Request from {client_ip or 'unknown'} - {user_agent or 'unknown'}")
    return {
        "user_agent": user_agent,
        "client_ip": client_ip
    }