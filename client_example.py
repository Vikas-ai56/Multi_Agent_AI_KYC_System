"""
TATA AIA KYC System Client
Example client for interacting with the FastAPI backend
"""

import requests
import json
import time
from typing import Optional, Dict, Any

class KYCAPIClient:
    """Client for interacting with the TATA AIA KYC API"""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session_id: Optional[str] = None
        
        # Setup session for connection pooling
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})
    
    def start_session(self, user_id: Optional[str] = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Start a new KYC session"""
        payload = {}
        if user_id:
            payload["user_id"] = user_id
        if metadata:
            payload["metadata"] = metadata
            
        response = self.session.post(
            f"{self.base_url}/api/v1/session/start",
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            self.session_id = data["session_id"]
            return data
        else:
            raise Exception(f"Failed to start session: {response.status_code} - {response.text}")
    
    def send_message(self, message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a message to the KYC system"""
        use_session_id = session_id or self.session_id
        
        if not use_session_id:
            raise Exception("No active session. Please start a session first.")
        
        payload = {
            "message": message,
            "session_id": use_session_id
        }
        
        response = self.session.post(
            f"{self.base_url}/api/v1/chat",
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to send message: {response.status_code} - {response.text}")
    
    def get_session_status(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get current session status"""
        use_session_id = session_id or self.session_id
        
        if not use_session_id:
            raise Exception("No active session.")
        
        response = self.session.get(f"{self.base_url}/api/v1/session/{use_session_id}/status")
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get session status: {response.status_code} - {response.text}")
    
    def end_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """End the current session"""
        use_session_id = session_id or self.session_id
        
        if not use_session_id:
            return {"message": "No active session to end"}
        
        response = self.session.delete(f"{self.base_url}/api/v1/session/{use_session_id}")
        
        if response.status_code == 200:
            if use_session_id == self.session_id:
                self.session_id = None
            return response.json()
        else:
            raise Exception(f"Failed to end session: {response.status_code} - {response.text}")
    
    def reset_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Reset the current session"""
        use_session_id = session_id or self.session_id
        
        if not use_session_id:
            raise Exception("No active session.")
        
        response = self.session.post(f"{self.base_url}/api/v1/session/{use_session_id}/reset")
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to reset session: {response.status_code} - {response.text}")
    
    def health_check(self) -> Dict[str, Any]:
        """Check API health"""
        response = self.session.get(f"{self.base_url}/health")
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Health check failed: {response.status_code} - {response.text}")
    
    def list_sessions(self) -> Dict[str, Any]:
        """List all active sessions (admin function)"""
        response = self.session.get(f"{self.base_url}/api/v1/sessions")
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to list sessions: {response.status_code} - {response.text}")

def interactive_demo():
    """Interactive demo of the KYC API client"""
    print("🏛️  TATA AIA KYC System - API Client Demo")
    print("=" * 50)
    
    # Initialize client
    client = KYCAPIClient()
    
    try:
        # Health check
        print("🔍 Checking API health...")
        health = client.health_check()
        print(f"✅ API Status: {health['status']}")
        print(f"📊 Active Sessions: {health['active_sessions']}")
        print("-" * 30)
        
        # Start session
        print("🚀 Starting new KYC session...")
        start_response = client.start_session(user_id="demo_user_001")
        print(f"📋 Session ID: {start_response['session_id']}")
        print(f"🤖 RIA: {start_response['response_to_user']}")
        print("-" * 50)
        
        # Interactive conversation
        while True:
            user_input = input("\n👤 You: ").strip()
            
            if user_input.lower() in ['exit', 'quit', 'bye']:
                break
            
            if user_input.lower() == 'status':
                # Show session status
                status = client.get_session_status()
                print(f"📊 Session Status:")
                print(f"   - Active Workflow: {status.get('active_workflow', 'None')}")
                print(f"   - KYC Step: {status.get('kyc_step', 'None')}")
                print(f"   - Completed: {', '.join(status.get('completed_workflows', [])) or 'None'}")
                continue
            
            if user_input.lower() == 'reset':
                # Reset session
                reset_response = client.reset_session()
                print(f"🔄 Session Reset")
                print(f"🤖 RIA: {reset_response['response_to_user']}")
                continue
            
            if not user_input:
                continue
            
            # Send message and get response
            try:
                response = client.send_message(user_input)
                print(f"🤖 RIA: {response['response_to_user']}")
                
                # Show progress if available
                status = client.get_session_status()
                if status.get('active_workflow'):
                    print(f"📋 [Progress: {status['active_workflow']} - {status.get('kyc_step', 'In Progress')}]")
                
            except Exception as e:
                print(f"❌ Error: {e}")
        
    except KeyboardInterrupt:
        print("\n\n🛑 Demo interrupted by user")
    except Exception as e:
        print(f"❌ Demo error: {e}")
    finally:
        # Clean up
        try:
            if client.session_id:
                client.end_session()
                print("✅ Session ended successfully")
        except:
            pass
        
        print("👋 Thank you for using TATA AIA KYC System!")

if __name__ == "__main__":
    interactive_demo()