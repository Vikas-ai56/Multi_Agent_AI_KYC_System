from typing_extensions import TypedDict, Optional, List, Dict, Literal
from pydantic import BaseModel, Field


class PANDetailsState(TypedDict):
    pan_card_number: str = Field(description="The PAN card number of the user")
    date_of_birth: str = Field(description="THE customers date of birth in DD/MM/YYYY format")
    pan_card_holders_name: str = Field(description="The name of the user as written on the PAN card")

class VerificationState(TypedDict):
    verification_status: str = Field(description="Status of PAN verification: success, failed, or error")
    verification_message: str = Field(description="Verification result message")
    verification_timestamp: str = Field(description="Timestamp when verification was performed")
    verification_doc: str = Field(description="The document which was used for verification")

class AadharDetailsState(TypedDict):
    aadhar_number: str = Field(description="The Aadhar card number of the user")
    date_of_birth: str = Field(description="DD/MM/YYYY")
    name: str = Field(description="The name of the user")
    new_doc_needed: bool = Field(description="Whether a new document is needed for age proof")
    
class VoterIdDetailsState(TypedDict):
    name: str = Field(description="The name of the user")
    dob: str = Field(description="DD/MM/YYYY")
    voter_id: str = Field(description="The Voter ID of the user")
    new_doc_needed: bool = Field(description="Whether a new document is needed for age proof")

class Form60DetailsState(TypedDict):
    agricultural_income: int = Field(description="Ask the user for his income with agricultural as source", default=0)
    other_income: int = Field(description="Ask if the user has any other source of income", default=0)

class Form60Data(TypedDict, total=False):
    agricultural_income: int
    other_income: int
class OverallState(TypedDict):
    session_id: str
    active_workflow: Optional[str]
    completed_workflows: List[str]
    kyc_step: Optional[str] # e.g., 'awaiting_pan_input', 'awaiting_confirmation'

    # --- High-Level Control Flags ---
    pan_probe_complete: bool

    # --- Logging & Context ---
    last_user_message: str
    last_agent_response: str
    
    # --- Data Payloads from Specialist Agents ---
    aadhar_details: AadharDetailsState
    pan_details: PANDetailsState
    Form_60: Form60Data
    # voterId_details: VoterIdDetailsState # For future use

    # --- Verification Status Payloads ---
    aadhar_verification_status: VerificationState
    pan_verification_status: VerificationState

class PanGraphState(TypedDict):
    """The state object that is passed between nodes in the PAN workflow graph."""
    session_id: str
    user_message: str
    aadhaar_details: Optional[dict]
    
    # Internal State
    pan_details: dict
    retries: int
    decision: Optional[str]

    last_executed_node: str
    response_to_user: str
    status: Literal["IN_PROGRESS", "SUCCESS", "FAILURE"]


class AadharGraphState(TypedDict):
    """The state object that is passed between nodes in the Aadhaar workflow graph."""
    # Input from the main orchestrator
    session_id: str
    user_message: str
    decision: Optional[str]
    
    # Internal state for the Aadhaar workflow
    retries: int
    otp_retries: int
    aadhaar_no: str
    verified_data: Optional[Dict] # Temporarily hold data before committing to OverallState
    
    # The final output to be sent to the user
    response_to_user: str
    last_executed_node: str
    status: Literal["IN_PROGRESS", "SUCCESS", "FAILURE"]
class Form60GraphState(TypedDict):
    """The state object for the Form60 workflow graph."""
    session_id: str
    user_message: str
    retries: int
    
    # Internal State
    form60_data: Form60Data
    current_question: Literal["agri", "other"]

    # Execution Tracking
    last_executed_node: str
    response_to_user: str
    status: Literal["IN_PROGRESS", "SUCCESS", "FAILURE"]
    decision: Optional[str]