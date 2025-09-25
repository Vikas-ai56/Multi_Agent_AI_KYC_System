# TATA AIA KYC System

A FastAPI-based multi-agent KYC system for TATA AIA Life Insurance with comprehensive webhook support.

## Features

- 🤖 **Multi-Agent AI System**: Specialized agents for PAN, Aadhaar, and Form 60 processing
- 🚀 **FastAPI Backend**: Modern, async API with automatic documentation
- 📡 **Webhook Support**: Real-time event notifications for external integrations
- 🔄 **Session Management**: Persistent conversation sessions with state management
- 📊 **Fixed Response Model**: Consistent API responses with `ResponseModel`
- 🐳 **Docker Support**: Complete containerization with Docker Compose
- 🔒 **Production Ready**: Security, logging, and monitoring features

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the API Server

```bash
python run_api.py
```

The API will be available at `http://localhost:8000`

### 3. Interactive Demo

```bash
python client_example.py
```

## API Endpoints

### Core Endpoints

- `POST /api/v1/session/start` - Start a new KYC session
- `POST /api/v1/chat` - Send message to KYC agent
- `GET /api/v1/session/{session_id}/status` - Get session status
- `DELETE /api/v1/session/{session_id}` - End session

### Webhook Endpoints

- `POST /webhook/register` - Register webhook URL
- `POST /webhook/receive` - Receive external webhooks

### Monitoring

- `GET /health` - Health check
- `GET /sessions` - List active sessions (admin)

## Response Model

All endpoints return the fixed `ResponseModel`:

```python
class ResponseModel(BaseModel):
    response_to_user: str
    session_id: str
```

## Example Usage

### Start Session and Chat

```python
import requests

# Start session
response = requests.post("http://localhost:8000/api/v1/session/start")
session_data = response.json()
session_id = session_data["session_id"]

# Send message
chat_response = requests.post("http://localhost:8000/api/v1/chat", json={
    "message": "I have my PAN card ready",
    "session_id": session_id
})

print(chat_response.json()["response_to_user"])
```

### Using the Client

```python
from client_example import KYCAPIClient

client = KYCAPIClient()
session = client.start_session(user_id="user123")
response = client.send_message("I have PAN card")
print(response["response_to_user"])
```

## Webhook Events

The system triggers webhooks for these events:

- `session_start` - New KYC session created
- `message_processed` - User message processed
- `session_end` - Session terminated
- `session_reset` - Session reset to initial state

### Webhook Payload

```python
{
    "event_type": "message_processed",
    "session_id": "api-session-...",
    "data": {
        "user_message": "I have PAN card",
        "ai_response": "Great! Please provide...",
        "active_workflow": "pan_workflow",
        "kyc_step": "document_upload"
    },
    "timestamp": "2025-09-19T10:30:00"
}
```

## Docker Deployment

### Development

```bash
docker-compose up -d
```

### Production

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
ENVIRONMENT=production
DEBUG=false
HOST=0.0.0.0
PORT=8000
REDIS_URL=redis://redis:6379
WEBHOOK_SECRET=your-secret-key
```

### Settings

All settings are managed in `config/settings.py` with Pydantic validation.

## Architecture

```
├── app/
│   ├── main.py          # FastAPI application
│   ├── models.py        # Pydantic models
│   ├── dependencies.py  # Dependency injection
│   └── routers/
│       └── chat.py      # Chat endpoints
├── config/
│   └── settings.py      # Configuration
├── agent/               # AI agents
├── orchestrator/        # Agent orchestration
├── memory/              # Session memory
└── tools/               # KYC tools
```

## Session State Management

Sessions maintain state across conversations:

```python
{
    "session_id": "api-session-uuid",
    "active_workflow": "pan_workflow",
    "kyc_step": "document_verification",
    "completed_workflows": ["aadhaar_workflow"],
    "pan_details": {...},
    "aadhar_details": {...}
}
```

## Development

### Run in Development Mode

```bash
python run_api.py development
```

### Run Tests

```bash
pytest tests/
```

### API Documentation

Visit `http://localhost:8000/docs` for interactive API documentation.

## Production Considerations

1. **Database**: Use PostgreSQL instead of in-memory storage
2. **Redis**: Use Redis for session management
3. **Security**: Configure proper CORS, API keys, and rate limiting
4. **Monitoring**: Set up logging, metrics, and health checks
5. **Load Balancing**: Use multiple worker processes
6. **SSL**: Configure HTTPS with proper certificates

## Webhook Integration Examples

### Register Webhook

```bash
curl -X POST "http://localhost:8000/webhook/register" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://your-system.com/kyc-webhook",
    "event_types": ["session_start", "message_processed", "session_end"]
  }'
```

### Webhook Receiver Example

See `webhook_example.py` for a complete webhook receiver implementation.

## Support

For issues and questions, please refer to the documentation or create an issue in the repository.

## License

TATA AIA Life Insurance - Internal Use