    
import re
import pandas as pd
import os
from typing import Optional, Dict
from pydantic import BaseModel
from state import PANDetailsState # Assuming this is your TypedDict

class VerificationResult(BaseModel):
    status: str  # "success", "failed", or "error"
    message: str
    verified_data: Optional[Dict] = None

# --- Database Setup (as a reusable function) ---
def get_nsdl_database():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Go up to project root
    db_folder = os.path.join(BASE_DIR, "data")
    db_path = os.path.join(db_folder, "database_nsdl.csv")  # Correct filename
    return pd.read_csv(db_path)

# --- Tool 1: Format Validation (from your _verify method) ---
def validate_pan_format(pan_number: str) -> bool:
    """Checks if the provided string is a valid 10-character PAN format."""
    match = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]{1}", pan_number.strip().upper())
    pan_number = match.group(0)
    
    if pan_number is not None:
        return True
    return False

def validate_dob_format(dob: str) -> bool:
    """Checks if the provided string is a valid DD/MM/YYYY format."""
    match = re.search(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", dob.strip())
    dob = match.group(0)
    
    if dob is not None:
        return True
    return False

# --- Tool 2: Database Verification (from your verify_from_NSDL method) ---
def verify_pan_in_nsdl(pan_details: PANDetailsState) -> VerificationResult:
    """
    Verifies a user's PAN details against the NSDL database.
    Returns a structured VerificationResult.
    """
    try:
        df = get_nsdl_database()
        pan_number = pan_details.get("pan_card_number", "").strip().upper()
        dob = pan_details.get("date_of_birth", "").strip()
        name = pan_details.get("pan_card_holders_name", "").strip().upper()

        if not all([pan_number, dob, name]):
            return VerificationResult(status="error", message="Missing required details for NSDL verification.")

        mask = (
            (df['pan_card_number'].str.strip().str.upper() == pan_number) &
            (df['date_of_birth'].str.strip() == dob) &
            (df['pan_card_holders_name'].str.strip().str.upper() == name)
        )
        
        if not df[mask].empty:
            return VerificationResult(status="success", message="PAN details verified successfully in NSDL.")
        else:
            return VerificationResult(status="failed", message="Details did not match any record in the NSDL database.")

    except Exception as e:
        return VerificationResult(status="error", message=f"An unexpected error occurred during NSDL lookup: {str(e)}")

# --- Tool 3: Data Comparison (from your cmp_data method) ---
def compare_pan_and_aadhaar_data(pan_details: dict, aadhaar_details: dict) -> bool:
    """Compares name and DOB between verified PAN and Aadhaar details."""
    pan_name = pan_details.get("pan_card_holders_name", "").strip().upper()
    pan_dob = pan_details.get("date_of_birth", "").strip()
    
    aadhaar_name = aadhaar_details.get("name", "").strip().upper()
    aadhaar_dob = aadhaar_details.get("date_of_birth", "").strip()
    
    return pan_name == aadhaar_name and pan_dob == aadhaar_dob

# --- Tool 4: Income Validation (from your _accept_form60 method) ---
def validate_income_format(income_str: str) -> bool:
    """Checks if the provided string is a valid integer."""
    try:
        int(income_str)
        return True
    except ValueError:
        return False