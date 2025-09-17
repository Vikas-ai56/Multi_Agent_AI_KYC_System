import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import requests
import time
from typing import Union, Dict
from config.config import get_settings
from pathlib import Path
import base64

class DocumentIntelligenceService:
    """
    Service for Azure Document Intelligence REST API (prebuilt models like Read/Layout).
    Mirrors the gist’s structure and supports local image bytes upload or URL JSON.
    """

    def __init__(self):
        settings = get_settings()
        self.key = settings.document_intelligence.api_key
        self.endpoint = settings.document_intelligence.endpoint
        self.api_version = "2024-11-30"
        
    def analyze(
        self,
        source: Union[str, bytes, Path],
        is_url: bool = False,
        model_id: str = "prebuilt-read",
    ) -> Dict:
        
        result_id = self._submit_analysis(source, is_url, model_id)
        return self._get_analysis_results(result_id, model_id)

    def _submit_analysis(
        self,
        source: Union[str, bytes, Path],
        is_url: bool,
        model_id: str,
    ) -> str:
        
        url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}:analyze?api-version={self.api_version}&outputContentFormat=markdown"

        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type" : "application/json"
        }

        logging.info("Submitting document for analysis")

        if is_url:
            payload = {"urlSource": source}
            response = requests.post(url, headers=headers, json=payload)
        else:
            base64_str = self._resolve_bytes_and_type(source)
            payload = {"base64Source": base64_str}
            response = requests.post(url, headers=headers, json=payload)

        response.raise_for_status()

        operation_location = response.headers.get("Operation-Location")
        
        if not operation_location:
            raise ValueError("Operation-Location header is missing in the response.")
        
        return operation_location.split("/")[-1].split("?")[0]

    def _get_analysis_results(self, result_id: str, model_id: str) -> Dict:
        
        url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}/analyzeResults/{result_id}?api-version={self.api_version}&outputContentFormat=markdown"
        headers = {"Ocp-Apim-Subscription-Key": self.key}

        while True:
            logging.info("Waiting for analysis to complete.")
            time.sleep(2)

            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status in ["succeeded", "failed"]:
                return data

    def _resolve_bytes_and_type(self, source: Union[bytes, Path, str]):
        """
        Accept raw bytes, file path (Path/str). Detect proper content-type for recognized formats.
        Supported: JPEG, PNG, JPG.
        """

        file_bytes = Path(source).read_bytes()
        base64_str = base64.b64encode(file_bytes).decode("utf-8")
        return base64_str

if __name__ == "__main__":
    client = DocumentIntelligenceService()
    results = client.analyze(
        source=Path(r"D:\test_pan.jpg"),       # local file on disk
        is_url=False,                          # upload as bytes
        model_id="prebuilt-read",                # Markdown content                     
    )

    print(results.get("status"))

    if results.get("status") == "succeeded":
        ar = results.get("analyzeResult", {})
        print(ar.keys())
