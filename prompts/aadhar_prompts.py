"""
Aadhar agent-specific prompts for the KYC system.
"""

AADHAR_REQUEST_PROMPT = """
Please enter your 12-digit Aadhaar number to begin verification.
Your data is encrypted and used only for KYC verification.
"""

AADHAR_RETRY_PROMPT = """
The number wasn't valid. Please enter your 12-digit Aadhaar number again.
Remember: Only numbers (0-9), no spaces or special characters.
"""

OTP_REQUEST_PROMPT = """
A 6-digit OTP has been sent to your Aadhaar-linked mobile number.
Please enter the OTP to verify your identity.
"""

OTP_RETRY_PROMPT = """
Incorrect OTP. A new 6-digit code has been sent.
Please check your messages and enter the new OTP.
"""

DB_VERIFICATION_FAILED = """
We couldn't verify your Aadhaar in the database. This could mean:
• Incorrect number entered
• System issue
• Details need updating

Would you like to try again or contact support?
"""

CONFIRMATION_PROMPT = """
Verified! Please confirm these details:
• Name: {name}
• Date of Birth: {dob}
• Aadhaar: {aadhar}
• Address: {address}

Are these correct? (Yes/No)
"""

DATA_MISMATCH_PROMPT = """
The details don't match your records. Please:
1. Visit uidai.gov.in to update your Aadhaar details
2. Return here after updating

We'll pause verification for now.
"""

VERIFICATION_SUCCESS = """
Aadhaar verification complete! Your details are securely recorded.
We can now proceed with the next step.
"""

VERIFICATION_TERMINATED = """
Verification was terminated due to failed attempts.

• Please verify your details at uidai.gov.in or contact support.

But not to worry, you can upload your passport/DL image whichever you have available with you right now.
Please let me which document you have available with you right now, So that we can proceed with the verification.
PASSPORT/DL??
"""