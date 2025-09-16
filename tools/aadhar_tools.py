import pandas as pd
from pydantic import BaseModel, Field
import os
from typing_extensions import Optional
import re


# In a real app, this would be a proper database connection.
# For now, we load the CSV as you did.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Go up one more level to reach project root
db_folder = os.path.join(BASE_DIR, "data")
db_path = os.path.join(db_folder, "database_uidai.csv")
UIDAI_DF = pd.read_csv(db_path, dtype={'aadhar_number': str})


class AadhaarDetails(BaseModel):
    """Data model for verified Aadhaar details."""
    name: str
    date_of_birth: str
    aadhar_number: str

class VerificationResult(BaseModel):
    """Standardized result for a verification tool."""
    status: str # "success", "failed", or "error"
    message: str
    verified_data: Optional[AadhaarDetails] = None

# -----------------------------------------------------------------------------
# AADHAR VERIFICATION TOOL
# -----------------------------------------------------------------------------

def validate_aadhaar_format(aadhaar_number: str) -> bool:
    print(f"--- TOOL: Validating Aadhaar format for '{aadhaar_number}' ---")
    aadhar_no_pattern = r"[0-9]{12}"
    match = re.search(aadhar_no_pattern, aadhaar_number)

    if match:
        aadhaar_number = match.group(0)
        return True
    
    return False

# -----------------------------------------------------------------------------
# OTP VERIFICATION TOOL
# -----------------------------------------------------------------------------

def validate_otp_format(otp: str) -> bool:
    print(f"--- TOOL: Validating OTP format for '{otp}' ---")
    otp_pattern = r'[0-9]{6}'
    match = re.search(otp_pattern, otp)

    if match:
        return True
    return False
# -----------------------------------------------------------------------------
# EKYC TOOL
# -----------------------------------------------------------------------------

def verify_aadhaar_in_database(aadhaar_number: str) -> VerificationResult:
    """
    Verifies a 12-digit Aadhaar number against the internal UIDAI database.
    Returns the user's details if found, otherwise returns a failure status.
    """
    print(f"--- TOOL: Verifying Aadhaar '{aadhaar_number}' in database ---")
    try:
        mask = UIDAI_DF['aadhar_number'].str.strip() == aadhaar_number.strip()
        matching_records = UIDAI_DF[mask]
        
        if not matching_records.empty:
            record = matching_records.iloc[0]
            details = AadhaarDetails(
                aadhar_number=record["aadhar_number"],
                date_of_birth=record["date_of_birth"],
                name=record["name"]
            )
            return VerificationResult(
                status="success",
                message="Aadhaar details verified successfully.",
                verified_data=details
            )
        else:
            return VerificationResult(
                status="failed",
                message="Aadhaar number not found in the database."
            )
    except Exception as e:
        return VerificationResult(status="error", message=f"An unexpected error occurred: {str(e)}")
