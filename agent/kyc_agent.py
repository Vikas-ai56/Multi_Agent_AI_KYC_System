from typing import Tuple
from state import OverallState
from agent.aadhar_agent import AadharAgent
from agent.pan_agent import PanAgent
from agent.form60_agent import Form60Agent
from agent.passport_agent import PassportAgent
from agent.dl_agent import DLAgent
# from agents.specialists.form60_agent import Form60Agent

class KYCManagerAgent:
    """
    A middle-manager agent that delegates KYC tasks to the appropriate
    specialist document agent based on the active workflow.
    """
    def __init__(self):
        self.specialists = {
            "aadhaar": AadharAgent(),
            "pan": PanAgent(),
            "form60": Form60Agent(),
            "passport": PassportAgent(),
            "dl": DLAgent()
        }
        self.fallback_message = (
            "I'm sorry, there seems to be a system error and I can't determine which "
            "verification step we are on. Please contact support."
        )

    async def delegate_to_specialist(self, state: OverallState, user_message: str) -> Tuple[OverallState, str]:
        """
        1. Identifies the active workflow from the state.
        2. Routes the request to the corresponding specialist agent.
        """
        active_workflow = state.get("active_workflow")

        if not active_workflow:
            return state, self.fallback_message

        specialist_agent = self.specialists.get(active_workflow)

        if not specialist_agent:
            error_message = f"Error: No specialist agent found for the active workflow: '{active_workflow}'."
            print(error_message)
            return state, self.fallback_message

        return await specialist_agent.handle_step(state, user_message)