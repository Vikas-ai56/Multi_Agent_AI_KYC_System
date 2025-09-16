from abc import ABC, abstractmethod
from typing import Tuple
from state import OverallState

class BaseSpecialistAgent(ABC):
    """Abstract base class defining the contract for all specialist document agents."""

    @abstractmethod
    async def handle_step(self, state: OverallState, user_message: str):
        """
        Handles the current step of its specific workflow.
        Receives the full state and returns the updated state and a user-facing message.
        """
        pass