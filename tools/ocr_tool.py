from state import OverallState, PanGraphState
import time
import random
class OCR:
    def __init__(self):
        self.ocr_client = None

    def extract_ocr(self, state: OverallState):
        if not state["expired"]:
            print("upload an image of your pan card")
            time.sleep(2.0)
            print("Extracting OCR from image...")
            time.sleep(2.0)
            print("OCR Extraction Succesful")
        return state
    
    def pan_ocr(self, state: PanGraphState):
        # if not state["expired"]:
            print("upload an image of your pan card")
            time.sleep(2.0)
            print("Extracting OCR from image...")
            time.sleep(2.0)
            print("OCR Extraction Succesful")

            # ----------------------------------------------------------------------
            # Spoofing OCR extraction
            # ----------------------------------------------------------------------
            if random.randint(0,1) == 1:
                state["pan_details"]["pan_card_number"] = "ABCDE1234F"
                state["pan_details"]["date_of_birth"] = "01/01/1990"
                state["pan_details"]["pan_card_holders_name"] = "Ananya Sharma"
            else:
                state["pan_details"]["pan_card_number"] = "VWXYZ1234U"
                state["pan_details"]["date_of_birth"] = "01/01/1990"
                state["pan_details"]["pan_card_holders_name"] = "Ananya Sharma"
            # ----------------------------------------------------------------------

            return state