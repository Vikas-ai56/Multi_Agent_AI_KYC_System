from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class ResponseModel(BaseModel):
    """Fixed response model as requested by user"""
    response_to_user: str = Field(..., description="Response message to the user")
    session_id: str = Field(..., description="Unique session identifier")

class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    message: str = Field(..., description="User's message", min_length=1)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")

class ChatResponse(ResponseModel):
    """Response model for chat endpoint - inherits from ResponseModel"""
    pass

class SessionStartRequest(BaseModel):
    """Request model for starting a new session"""
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional session metadata")

class SessionStatusResponse(BaseModel):
    """Response model for session status"""
    session_id: str
    active_workflow: Optional[str]
    kyc_step: Optional[str]
    completed_workflows: List[str]
    is_active: bool
    created_at: Optional[str] = None
    last_activity: Optional[str] = None

class WebhookEvent(BaseModel):
    """Model for webhook events"""
    event_type: str = Field(..., description="Type of event (session_start, message_received, etc.)")
    session_id: str = Field(..., description="Session ID associated with the event")
    data: Optional[Dict[str, Any]] = Field(None, description="Event data payload")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class WebhookRegistration(BaseModel):
    """Model for webhook registration"""
    webhook_url: str = Field(..., description="URL to send webhook events to")
    event_types: List[str] = Field(..., description="List of event types to subscribe to")
    secret: Optional[str] = Field(None, description="Optional webhook secret for verification")

class WebhookResponse(BaseModel):
    """Response model for webhook operations"""
    webhook_id: str
    message: str
    status: str = "success"

class ErrorResponse(BaseModel):
    """Standard error response model"""
    error: str
    detail: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    active_sessions: int
    registered_webhooks: Optional[int] = None
    service: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class SessionListResponse(BaseModel):
    """Response model for listing sessions"""
    active_sessions: int
    sessions: List[SessionStatusResponse]