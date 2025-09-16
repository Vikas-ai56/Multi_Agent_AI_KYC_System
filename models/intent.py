# file: models/intents.py
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# still the intent for form60 has to be completed
class UserIntent(str, Enum):
    START_AADHAAR_VERIFICATION = "User wants to start the Aadhaar verification process."
    START_PAN_VERIFICATION = "User wants to start the PAN card verification process."
    CONTINUE_ACTIVE_WORKFLOW = "User is providing information for a currently active workflow."
    ASK_GENERAL_QUESTION = "User is asking a general question about insurance, not related to the KYC process."
    PROVIDE_CONFIRMATION_YES = "User is confirming 'Yes' to a question from an agent."
    PROVIDE_CONFIRMATION_NO = "User is confirming 'No' to a question from an agent."
    UNKNOWN = "The user's intent is unclear or irrelevant to the KYC or insurance process."

class OrchestratorDecision(BaseModel):
    """
    The structured output that the Main Orchestrator's LLM must generate.
    This provides a reliable, machine-readable format for routing.
    """
    intent: UserIntent = Field(
        description="The single most likely intent of the user, chosen from the available options."
    )
    argument: Optional[str] = Field(
        default=None,
        description="If the intent is ASK_GENERAL_QUESTION, this field should contain the specific question being asked. Otherwise, it should be null."
    )
    user_provides_data: bool = Field(
        description="Set to True if the user's message contains concrete data like a number, name, or date of birth. Set to False if it's a simple confirmation or question."
    )
    reason: str = Field(
        description = "This helps us in understanding why the LLM has decided this particular user intent"
    )