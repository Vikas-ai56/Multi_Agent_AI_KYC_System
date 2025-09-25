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
# Read all columns as strings to avoid type conversion issues
UIDAI_DF = pd.read_csv(db_path, dtype=str)


class AadhaarDetails(BaseModel):
    """Data model for verified Aadhaar details."""
    name: str
    date_of_birth: str
    aadhar_number: str
    address: str

class VerificationResult(BaseModel):
    """Standardized result for a verification tool."""
    status: str # "success", "failed", or "error"
    message: str
    verified_data: Optional[AadhaarDetails] = None

def mask_aadhaar(aadhaar_number: str) -> str:
    """Masks an Aadhaar number to show only last 4 digits."""
    return "XXXX XXXX " + aadhaar_number[-4:]

def format_address(row) -> str:
    """Formats the address components into a single string."""
    try:
        components = [
            str(row['house']).strip(),
            str(row['street']).strip(),
            str(row['lm']).strip() if pd.notna(row['lm']) else None,
            str(row['loc']).strip() if pd.notna(row['loc']) else None,
            str(row['vtc']).strip(),
            str(row['district']).strip(),
            str(row['state']).strip(),
            str(row['pincode']).strip()
        ]
        # Filter out None/NaN/empty values and join with commas
        return ', '.join(filter(lambda x: x and x != 'nan', components))
    except Exception as e:
        print(f"Error formatting address: {str(e)}")
        # Return a basic address if there's an error
        return f"{row['house']}, {row['street']}, {row['district']}, {row['state']}, {row['pincode']}"

# -----------------------------------------------------------------------------
# AADHAR VERIFICATION TOOL
# -----------------------------------------------------------------------------

def validate_aadhaar_format(aadhaar_number: str) -> bool:
    print(f"--- TOOL: Validating Aadhaar format for '{aadhaar_number}' ---")
    # Remove any spaces or hyphens that might be in the format
    cleaned_aadhaar = re.sub(r'[\s-]', '', aadhaar_number.strip())
    
    # Check if it's exactly 12 digits (no more, no less)
    aadhar_no_pattern = r"^[0-9]{12}$"
    match = re.match(aadhar_no_pattern, cleaned_aadhaar)

    if match:
        return True
    
    return False

# -----------------------------------------------------------------------------
# OTP VERIFICATION TOOL
# -----------------------------------------------------------------------------

def validate_otp_format(otp: str) -> bool:
    cleaned_otp = re.sub(r'\s', '', otp.strip())
    
    # Check if it's exactly 6 digits (no more, no less)
    otp_pattern = r'^[0-9]{6}$'
    match = re.match(otp_pattern, cleaned_otp)

    if match:
        return True
    return False

# -----------------------------------------------------------------------------
# EKYC TOOL
# Verifies aadhaar number and masks them for privacy
# -----------------------------------------------------------------------------

def verify_aadhaar_in_database(aadhaar_number: str) -> VerificationResult:
    """
    Verifies a 12-digit Aadhaar number against the internal UIDAI database.
    Returns the user's details if found, otherwise returns a failure status.
    """
    print(f"--- TOOL: Verifying Aadhaar '{aadhaar_number}' in database ---")
    try:
        # Convert input to string and strip whitespace
        aadhaar_number = str(aadhaar_number).strip()
        
        # Print debug info
        print(f"Looking for Aadhaar: '{aadhaar_number}'")
        print("First few Aadhaar numbers in DB:", UIDAI_DF['aadhar_number'].head().tolist())
        
        # Ensure exact string match
        mask = UIDAI_DF['aadhar_number'].astype(str).str.strip() == aadhaar_number
        matching_records = UIDAI_DF[mask]
        
        print(f"Found {len(matching_records)} matching records")
        
        if not matching_records.empty:
            record = matching_records.iloc[0]
            address = format_address(record)
            print(f"Formatted address: {address}")
            
            details = AadhaarDetails(
                aadhar_number=mask_aadhaar(record["aadhar_number"]),
                date_of_birth=record["date_of_birth"],
                name=record["name"],
                address=address
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
        print(f"Error during verification: {str(e)}")
        return VerificationResult(status="error", message=f"An unexpected error occurred: {str(e)}")