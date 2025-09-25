import asyncio
import uuid
from orchestrator.router import MainOrchestrator
from state import OverallState
from typing_extensions import cast

import traceback

from memory.memory import MemoryManager
from greet import generate_greeting_message

async def main():
    """
    Initializes the agent system and runs a command-line interface for interaction.
    """
    print("--- TATA AIA Conversational Agent ---")
    print("Type 'exit' or 'quit' to end the conversation.")

    greeting_message = generate_greeting_message()
    print("\n", "RIA: ",greeting_message)
    print("-" * 35)

    # 1. Create an initial state for the user's session.
    # In a real app, you would load this from a database using a session_id.
    session_id = f"cli-session-{uuid.uuid4()}"

    memory_client = MemoryManager(session_id)
    # 2. Initialize the Main Orchestrator
    orchestrator = MainOrchestrator(memory_client)
    
    # This dictionary MUST contain all the keys defined in your OverallState TypedDict.
    # We use `cast` to inform the type checker that this dictionary adheres to the TypedDict structure.
    state: OverallState = cast(OverallState, {
        "session_id": session_id,
        "input_message": "",
        "ai_response": greeting_message,
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

    # 3. Start the conversational loop
    while True:
        try:
            # (your existing code)
            user_message = input("You: ")
            if user_message.lower() in ["exit", "quit"]:
                break
            if not user_message.strip():
                continue
            updated_state, response_message = await orchestrator.route(state, user_message)
            state = updated_state
            print(f"\nRIA: {response_message}\n")

        except KeyboardInterrupt:
            print("\n\nRIA: Conversation ended. Goodbye!")
            break
        except Exception as e:
            print("\n--- An unexpected error occurred ---")
            traceback.print_exc() 
            print("-" * 35)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Failed to start the application: {e}")