#!/usr/bin/env python3
"""
TATA AIA KYC System API Server
Run script for the FastAPI backend
"""

import uvicorn
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import settings

def main():
    """Main function to run the FastAPI server"""
    
    environment = os.getenv("ENVIRONMENT", "development")
    
    print(f"🚀 Starting TATA AIA KYC System API Server")
    print(f"📦 Environment: {environment}")
    print(f"🌐 Host: {settings.host}:{settings.port}")
    print(f"🔧 Debug: {settings.debug}")
    print(f"📝 Log Level: {settings.log_level}")
    print("-" * 50)
    
    # Configure uvicorn settings
    uvicorn_config = {
        "app": "app.main:app",
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
        "log_level": settings.log_level.lower(),
        "access_log": True,
        "use_colors": True,
    }
    
    # Additional production settings
    if environment == "production":
        uvicorn_config.update({
            "workers": 4,  # Multiple worker processes
            "reload": False,
            "access_log": True,
        })
    
    try:
        # Start the server
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()