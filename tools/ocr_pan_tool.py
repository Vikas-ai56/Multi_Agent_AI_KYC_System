import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from typing import Dict, Optional
from pathlib import Path
from PIL import Image
import re

TEMPLATE = """आयकर विभाग INCOME TAX DEPARTMENT
सत्यमेव जयते
भारत सरकार GOVT. OF INDIA
स्थायी लेखा संख्या कार्ड Permanent Account Number Card
_____________
नाम / Name
_____________
पिता का नाम / Father's Name ________________
जन्म की तारीख / Date of Birth _______________
हस्ताक्षर / Signature

NOTE:- Fields may be re-ordered as well.
"""

class PanProcessor:

    def validate_image_file(self, file_path: Path) -> dict:
        """
        Validate image file before processing.
        """
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            if not file_path.exists():
                validation_result["is_valid"] = False
                validation_result["errors"].append("File does not exist")
                return validation_result
            
            allowed_extensions = {'.jpg', '.jpeg', '.png'}
            if file_path.suffix.lower() not in allowed_extensions:
                validation_result["is_valid"] = False
                validation_result["errors"].append(f"Unsupported file format: {file_path.suffix}")
            
            try:
                with Image.open(file_path) as img:
                    width, height = img.size
                    
                    if width < 300 or height < 200:
                        validation_result["warnings"].append("Image resolution is very low. OCR accuracy may be reduced.")
                    
                    if width > 4000 or height > 4000:
                        validation_result["warnings"].append("Image resolution is very high. Processing may be slow.")
                    
            except Exception as e:
                validation_result["is_valid"] = False
                validation_result["errors"].append(f"Invalid or corrupted image file: {str(e)}")
        
        except Exception as e:
            validation_result["is_valid"] = False
            validation_result["errors"].append(f"File validation error: {str(e)}")
        
        return validation_result


    def validate_ocr_content(self, content: str) -> dict:
            """
            Validate if OCR content looks like a PAN card.
            """
            validation = {
                "is_pan_card": False,
                "confidence": 0,
                "issues": []
            }
            
            if not content or len(content.strip()) < 20:
                validation["issues"].append("Very little text detected - image may be unclear or not a document")
                return validation
            
            pan_indicators = 0
            
            if re.search(r'[A-Z]{5}[0-9]{4}[A-Z]{1}', content):
                pan_indicators += 3
            
            hindi_patterns = ['नाम', 'पिता', 'जन्म', 'हस्ताक्षर']
            english_patterns = ['Name', 'Father', 'Birth', 'Signature', 'INCOME TAX', 'GOVT']
            
            for pattern in hindi_patterns + english_patterns:
                if pattern in content:
                    pan_indicators += 1
            
            if re.search(r'\d{1,2}\/\d{1,2}\/\d{4}', content):
                pan_indicators += 2
            
            validation["confidence"] = min(pan_indicators * 10, 100) 
            validation["is_pan_card"] = pan_indicators >= 4
            
            if not validation["is_pan_card"]:
                validation["issues"].append("Document does not appear to be a PAN card")
            
            return validation

    def extract_pan_details(self, ocr_text: str) -> Dict[str, Optional[str]]:

        """
        Extract PAN card details from OCR text automatically.
        """
        pan_details = {
            "permanent_account_number": None,
            "name": None,
            "date_of_birth": None
        }
        
        cleaned_text = ' '.join(ocr_text.split())
        
        pan_pattern = r'[A-Z]{5}[0-9]{4}[A-Z]{1}'
        pan_match = re.search(pan_pattern, cleaned_text)
        if pan_match:
            pan_details["permanent_account_number"] = pan_match.group()
        
        name_patterns = [
            r'(?:नाम\s*/\s*Name|Name)\s+([A-Z\s]+?)(?:\s+(?:पिता|Father|जन्म|Date)|$)',
            r'Name\s+([A-Z\s]+?)(?:\s+(?:Father|Date)|$)'
        ]
        
        for pattern in name_patterns:
            name_match = re.search(pattern, cleaned_text, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
                name_words = name.split()
                
                if len(name_words) <= 3:
                    pan_details["name"] = name
                else:
                    pan_details["name"] = ' '.join(name_words[:3])
                break
        
        # father_patterns = [
        #     r'(?:पिता\s*का\s*नाम\s*/\s*Father\'?s?\s*Name|Father\'?s?\s*Name)\s+([A-Z\s]+?)(?:\s+(?:जन्म|Date|हस्ताक्षर)|$)',
        #     r'Father\'?s?\s*Name\s+([A-Z\s]+?)(?:\s+(?:Date|Signature)|$)'
        # ]
        
        # for pattern in father_patterns:
        #     father_match = re.search(pattern, cleaned_text, re.IGNORECASE)
        #     if father_match:
        #         father_name = father_match.group(1).strip()
        #         # Clean up father's name
        #         father_words = father_name.split()
        #         if len(father_words) <= 3:
        #             pan_details["father_name"] = father_name
        #         else:
        #             pan_details["father_name"] = ' '.join(father_words[:3])
        #         break
        
        dob_patterns = [
            r'(?:जन्म\s*की\s*तारीख\s*/\s*Date\s*of\s*Birth|Date\s*of\s*Birth)\s+(\d{1,2}\/\d{1,2}\/\d{4})',
            r'Date\s*of\s*Birth\s+(\d{1,2}\/\d{1,2}\/\d{4})',
            r'(\d{1,2}\/\d{1,2}\/\d{4})'  
        ]
        
        for pattern in dob_patterns:
            dob_match = re.search(pattern, cleaned_text, re.IGNORECASE)
            if dob_match:
                pan_details["date_of_birth"] = dob_match.group(1)
                break
        
        return pan_details

