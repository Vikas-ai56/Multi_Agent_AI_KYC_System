from typing_extensions import TypedDict, Optional, List, Dict
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

class OverallState(TypedDict):
    active_workflow: Optional[str] = Field(description="Name of the document workflow currently in progress, e.g., 'aadhaar' or 'pan'")
    completed_workflows: List[str] = Field(description="A list of document workflows that have been successfully completed.")
    kyc_step: Optional[str] = Field(description="The current step within the active_workflow.")
    
    input_message: str = Field(description="The response from the user")
    ai_response: str = Field(description="The response from the LLM")
    human_response: str = Field(description="The response from the User for available document")
    OTP_verified: bool = Field(default=False)
    expired: bool = Field(default= False)
    match: bool = Field(default=False)
    no_pan: bool = Field(default=True)
    Form_60: Form60DetailsState = Field(description="Stores form60 details")
    pan_details: PANDetailsState = Field(description="The PAN card details of the user")
    pan_verification_status: VerificationState = Field(description="Status of PAN verification: success, failed, or error")
    aadhar_details: AadharDetailsState = Field(description="The Aadhar card details of the user")
    aadhar_verification_status: VerificationState = Field(description="Status of AADHAR verification: success, failed, or error")
    voterId_details: VoterIdDetailsState = Field(description="The Voter ID card details of the user")
    user_message: str = Field(description="The response from the user")


class PanGraphState(TypedDict):
    """The state object that is passed between nodes in the PAN workflow graph."""
    # Input from the main orchestrator
    session_id: str
    user_message: str
    
    # Data from the OverallState
    aadhaar_details: Optional[AadharDetailsState]
    
    # Internal state for the PAN workflow
    pan_details: PANDetailsState
    retries: int
    
    # The final output to be sent to the user
    response_to_user: str
    last_executed_node: str


class AadharGraphState(TypedDict):
    """The state object that is passed between nodes in the Aadhaar workflow graph."""
    # Input from the main orchestrator
    session_id: str
    user_message: str
    
    # Internal state for the Aadhaar workflow
    retries: int
    verified_data: Optional[Dict] # Temporarily hold data before committing to OverallState
    
    # The final output to be sent to the user
    response_to_user: str
    last_executed_node: str