from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid
import logging
from typing import Dict, Any
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from .routers import chat
from .models import WebhookEvent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory session storage (use Redis/Database in production)
active_sessions: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting TATA AIA KYC FastAPI Server...")
    yield
    # Shutdown
    logger.info("Shutting down TATA AIA KYC FastAPI Server...")

app = FastAPI(
    title="TATA AIA KYC System",
    description="Multi-Agent AI KYC System for TATA AIA Life Insurance",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])

# Global webhook storage (use proper database/queue in production)
webhook_callbacks: Dict[str, Dict[str, Any]] = {}

async def trigger_webhook(event: WebhookEvent):
    """Trigger registered webhooks for specific events"""
    logger.info(f"Webhook triggered: {event.event_type} for session {event.session_id}")
    # In production, implement actual HTTP calls to registered webhook URLs
    # Example: Send POST requests to registered webhook endpoints
    pass

@app.post("/webhook/register")
async def register_webhook(webhook_url: str, event_types: list[str]):
    """Register a webhook URL for specific event types"""
    webhook_id = str(uuid.uuid4())
    webhook_callbacks[webhook_id] = {
        "url": webhook_url,
        "events": event_types,
        "created_at": datetime.utcnow().isoformat()
    }
    return {"webhook_id": webhook_id, "message": "Webhook registered successfully"}

@app.post("/webhook/receive")
async def receive_webhook(event: WebhookEvent):
    """Receive webhook from external systems"""
    logger.info(f"Received webhook: {event.event_type} for session {event.session_id}")
    
    # Process the webhook event
    # Add your external system integration logic here
    
    return {
        "status": "webhook_received", 
        "event_type": event.event_type,
        "session_id": event.session_id
    }

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main chat interface"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_sessions": len(active_sessions),
        "registered_webhooks": len(webhook_callbacks),
        "service": "TATA AIA KYC System"
    }

@app.get("/sessions")
async def list_active_sessions():
    """List all active sessions (for admin/monitoring)"""
    return {
        "active_sessions": len(active_sessions),
        "sessions": [
            {
                "session_id": sid,
                "active_workflow": data["state"].get("active_workflow"),
                "kyc_step": data["state"].get("kyc_step"),
                "completed_workflows": data["state"].get("completed_workflows", [])
            }
            for sid, data in active_sessions.items()
        ]
    }

# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {str(exc)}")
    return HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )