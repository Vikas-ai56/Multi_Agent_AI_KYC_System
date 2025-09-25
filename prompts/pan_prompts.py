"""
PAN agent-specific prompts for the KYC system.
"""

PAN_PREFILLED_PROMPT = """
Please provide your 10-character PAN number.
This helps verify your tax registration status.
"""

PAN_MANUAL_PROMPT = """
Please provide:
1. PAN number (10 characters)
2. Full name (as on PAN card)
3. Date of birth (DD/MM/YYYY)
"""

PAN_MANUAL_RETRY_PROMPT = """
Some details were incorrect. Please provide:
• PAN: 10 characters (e.g., ABCDE1234F)
• Name: As on PAN card
• DOB: DD/MM/YYYY format
"""

PAN_CORRECTION_PROMPT = """
Let's correct your details. Please provide:

PLEASE RE-ENTER ONLY THE DETAILS YOU WANT TO CHANGE.
FORMAT:- Field Name: New Value

Example:
1. PAN: ABCDE1234F
2. Name: John Doe
3. DOB: 01/01/1990
"""

PAN_CONFIRMATION_PROMPT = """
Please confirm these details:
• PAN: {pan}
• Name: {name}
• DOB: {dob}

Are they correct? (Yes/No)
"""

PAN_VERIFICATION_SUCCESS = """
PAN verification successful!
Your details are confirmed and recorded.
"""

PAN_VERIFICATION_FAILED = """
Verification failed. You can:
1. Re-check your details
2. Update at protean-tinpan.com
3. Contact support

Try again?
"""

PAN_OCR_REQUEST = """
Please upload a clear photo of your PAN card.
Ensure all text is readable and all corners are visible.
"""

PAN_TERMINATION = """
Verification was not successuful. Please:
1. Verify details at protean-tinpan.com
2. Contact support if needed

No worries, You have to fill "Form60" now. 
Our company will verify your details later.
"""