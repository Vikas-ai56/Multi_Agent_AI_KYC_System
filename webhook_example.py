"""
Example Webhook Receiver Service
Demonstrates how to receive webhooks from the KYC system
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uvicorn
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="KYC Webhook Receiver", version="1.0.0")

class WebhookPayload(BaseModel):
    event_type: str
    session_id: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str

@app.post("/webhook/kyc-events")
async def receive_kyc_webhook(payload: WebhookPayload):
    """Receive KYC system webhooks"""
    logger.info(f"📥 Received webhook: {payload.event_type} for session {payload.session_id}")
    
    # Process different event types
    if payload.event_type == "session_start":
        logger.info(f"🚀 New KYC session started: {payload.session_id}")
        user_id = payload.data.get("user_id") if payload.data else None
        if user_id:
            logger.info(f"👤 User ID: {user_id}")
    
    elif payload.event_type == "message_processed":
        if payload.data:
            user_msg = payload.data.get("user_message", "")
            ai_response = payload.data.get("ai_response", "")
            workflow = payload.data.get("active_workflow")
            step = payload.data.get("kyc_step")
            
            logger.info(f"💬 Message exchange:")
            logger.info(f"   User: {user_msg[:100]}...")
            logger.info(f"   AI: {ai_response[:100]}...")
            
            if workflow:
                logger.info(f"🔄 Current workflow: {workflow} - {step}")
    
    elif payload.event_type == "session_end":
        logger.info(f"🏁 Session ended: {payload.session_id}")
        if payload.data:
            completed = payload.data.get("completed_workflows", [])
            if completed:
                logger.info(f"✅ Completed workflows: {', '.join(completed)}")
    
    elif payload.event_type == "session_reset":
        logger.info(f"🔄 Session reset: {payload.session_id}")
    
    else:
        logger.info(f"❓ Unknown event type: {payload.event_type}")
    
    # Here you could:
    # - Store webhook data in database
    # - Send notifications to external systems
    # - Trigger business logic based on KYC progress
    # - Update customer records
    
    return {
        "status": "received",
        "event_type": payload.event_type,
        "session_id": payload.session_id,
        "processed_at": datetime.utcnow().isoformat()
    }

@app.post("/webhook/test")
async def test_webhook():
    """Test endpoint for webhook functionality"""
    logger.info("🧪 Test webhook received")
    return {"status": "test_received", "timestamp": datetime.utcnow().isoformat()}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "webhook_receiver"}

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "KYC Webhook Receiver Service",
        "endpoints": [
            "/webhook/kyc-events",
            "/webhook/test",
            "/health"
        ]
    }

if __name__ == "__main__":
    port = 8001
    logger.info(f"🎣 Starting Webhook Receiver on port {port}")
    uvicorn.run(
        "webhook_example:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=True
    )