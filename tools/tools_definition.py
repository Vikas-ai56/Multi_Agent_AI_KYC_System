AADHAAR_VERIFICATION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "verify_aadhaar_in_database",
        "description": "Verifies a 12-digit Aadhaar number against the internal UIDAI database to fetch user details.",
        "parameters": {
            "type": "object",
            "properties": {
                "aadhaar_number": {
                    "type": "string",
                    "description": "The 12-digit unique Aadhaar number provided by the user.",
                },
            },
            "required": ["aadhaar_number"],
        },
    }
}

AADHAAR_FORMAT_VALIDATION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_aadhaar_format",
        "description": "Validates if a given string follows the correct 12-digit format for an Aadhaar number. Does not check the database.",
        "parameters": {
            "type": "object",
            "properties": {"aadhaar_number": {"type": "string"}},
            "required": ["aadhaar_number"],
        },
    }
}

OTP_FORMAT_VALIDATION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_otp_format",
        "description": "Validates if a given string follows the correct 6-digit format for an OTP.",
        "parameters": {
            "type": "object",
            "properties": {"otp": {"type": "string"}},
            "required": ["otp"],
        },
    }
}