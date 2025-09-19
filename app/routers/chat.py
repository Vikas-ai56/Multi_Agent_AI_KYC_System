import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from typing import Dict, Any
from typing_extensions import cast

from ..models import (
    ChatRequest, 
    ChatResponse, 
    SessionStartRequest, 
    SessionStatusResponse,
    WebhookEvent,
    ErrorResponse
)
from ..dependencies import validate_session_id, get_current_session
from orchestrator.router import MainOrchestrator
from state import OverallState
from memory.memory import MemoryManager

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active sessions (in production, use Redis or database)
active_sessions: Dict[str, Dict[str, Any]] = {}

GREETING_PROMPT = (
    "Namaste I am RIA an insurance agent working for tata AIA\n"
    "I am here to help you complete your KYC verification process\n"
    "To kickstart this process I like to know which document is readily available with you now.\n"
    "PAN or AADHAAR?"
)

def create_initial_state(session_id: str) -> OverallState:
    """Create initial state for a new session using the same structure as main_cli.py"""
    return cast(OverallState, {
        "session_id": session_id,
        "input_message": "",
        "ai_response": GREETING_PROMPT,
        "active_workflow": None,
        "kyc_step": None,
        "completed_workflows": [],
        
        # Specialist Agent States
        "aadhar_details": {},
        "aadhar_verification_status": {},
        "aadhaar_retries": 0,
        
        "pan_details": {},
        "pan_verification_status": {},
        "pan_retries": 0,
        "match": None,
        
        "Form_60": {},
        
        "human_response": "" # Placeholder for human-in-the-loop
    })

async def trigger_webhook(event: WebhookEvent):
    """Trigger webhook for external systems integration"""
    logger.info(f"Webhook triggered: {event.event_type} for session {event.session_id}")
    # In production, implement actual HTTP calls to registered webhook URLs
    # Example: Send POST to external systems when KYC steps complete
    pass

@router.post("/session/start", response_model=ChatResponse)
async def start_session(
    request: SessionStartRequest,
    background_tasks: BackgroundTasks
):
    """Start a new KYC session"""
    try:
        # Generate new session ID
        session_id = f"api-session-{uuid.uuid4()}"
        
        # Initialize memory manager and orchestrator
        memory_client = MemoryManager(session_id)
        orchestrator = MainOrchestrator(memory_client)
        
        # Create initial state
        initial_state = create_initial_state(session_id)
        
        # Store session data
        active_sessions[session_id] = {
            "state": initial_state,
            "orchestrator": orchestrator,
            "memory_client": memory_client,
            "user_id": request.user_id,
            "metadata": request.metadata or {},
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        
        # Trigger webhook for session start
        webhook_event = WebhookEvent(
            event_type="session_start",
            session_id=session_id,
            data={
                "user_id": request.user_id,
                "metadata": request.metadata,
                "greeting": GREETING_PROMPT
            }
        )
        background_tasks.add_task(trigger_webhook, webhook_event)
        
        logger.info(f"New session started: {session_id}")
        
        return ChatResponse(
            response_to_user=GREETING_PROMPT,
            session_id=session_id
        )
        
    except Exception as e:
        logger.error(f"Error starting session: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to start session")

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks
):
    """Main chat endpoint for KYC conversation"""
    try:
        session_id = request.session_id
        
        # If no session_id provided, start a new session
        if not session_id:
            new_session_request = SessionStartRequest()
            return await start_session(new_session_request, background_tasks)
        
        # Validate session exists
        if session_id not in active_sessions:
            raise HTTPException(
                status_code=404, 
                detail="Session not found. Please start a new session using /session/start"
            )
        
        session_data = active_sessions[session_id]
        state = session_data["state"]
        orchestrator = session_data["orchestrator"]
        
        # Update last activity
        session_data["last_activity"] = datetime.utcnow().isoformat()
        
        # Process message through the existing orchestrator system
        try:
            updated_state, response_message = await orchestrator.route(state, request.message)
            
            # Update session state
            session_data["state"] = updated_state
            
        except Exception as e:
            logger.error(f"Error in orchestrator routing: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to process message")
        
        # Trigger webhook for message processing
        webhook_event = WebhookEvent(
            event_type="message_processed",
            session_id=session_id,
            data={
                "user_message": request.message,
                "ai_response": response_message,
                "active_workflow": updated_state.get("active_workflow"),
                "kyc_step": updated_state.get("kyc_step"),
                "completed_workflows": updated_state.get("completed_workflows", [])
            }
        )
        background_tasks.add_task(trigger_webhook, webhook_event)
        
        logger.info(f"Processed message for session {session_id}")
        
        return ChatResponse(
            response_to_user=response_message,
            session_id=session_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing chat message: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process message")

@router.get("/session/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(session_id: str = Depends(validate_session_id)):
    """Get current session status and progress"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = active_sessions[session_id]
    state = session_data["state"]
    
    return SessionStatusResponse(
        session_id=session_id,
        active_workflow=state.get("active_workflow"),
        kyc_step=state.get("kyc_step"),
        completed_workflows=state.get("completed_workflows", []),
        is_active=True,
        created_at=session_data.get("created_at"),
        last_activity=session_data.get("last_activity")
    )

@router.delete("/session/{session_id}")
async def end_session(
    session_id: str = Depends(validate_session_id),
    background_tasks: BackgroundTasks = None
):
    """End a KYC session and cleanup resources"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = active_sessions[session_id]
    
    # Trigger webhook for session end
    if background_tasks:
        webhook_event = WebhookEvent(
            event_type="session_end",
            session_id=session_id,
            data={
                "completed_workflows": session_data["state"].get("completed_workflows", []),
                "ended_at": datetime.utcnow().isoformat()
            }
        )
        background_tasks.add_task(trigger_webhook, webhook_event)
    
    # Clean up session
    del active_sessions[session_id]
    
    logger.info(f"Session ended: {session_id}")
    
    return {"message": "Session ended successfully", "session_id": session_id}

@router.get("/sessions")
async def list_active_sessions():
    """List all active sessions (admin endpoint)"""
    sessions = []
    for session_id, session_data in active_sessions.items():
        state = session_data["state"]
        sessions.append(SessionStatusResponse(
            session_id=session_id,
            active_workflow=state.get("active_workflow"),
            kyc_step=state.get("kyc_step"),
            completed_workflows=state.get("completed_workflows", []),
            is_active=True,
            created_at=session_data.get("created_at"),
            last_activity=session_data.get("last_activity")
        ))
    
    return {
        "active_sessions": len(sessions),
        "sessions": sessions
    }

@router.post("/session/{session_id}/reset")
async def reset_session(
    session_id: str = Depends(validate_session_id),
    background_tasks: BackgroundTasks = None
):
    """Reset a session to initial state"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = active_sessions[session_id]
    
    # Reset state to initial
    initial_state = create_initial_state(session_id)
    session_data["state"] = initial_state
    session_data["last_activity"] = datetime.utcnow().isoformat()
    
    # Trigger webhook for session reset
    if background_tasks:
        webhook_event = WebhookEvent(
            event_type="session_reset",
            session_id=session_id,
            data={"reset_at": datetime.utcnow().isoformat()}
        )
        background_tasks.add_task(trigger_webhook, webhook_event)
    
    logger.info(f"Session reset: {session_id}")
    
    return ChatResponse(
        response_to_user=GREETING_PROMPT,
        session_id=session_id
    )