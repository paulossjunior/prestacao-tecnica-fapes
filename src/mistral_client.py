"""Fábrica de cliente Mistral (compat SDK v1 e v2)."""
import os

try:
    from mistralai import Mistral  # SDK v1
except ImportError:
    from mistralai.client import Mistral  # SDK v2 (layout mudou)

DEFAULT_MODEL = "mistral-large-latest"
DEFAULT_OCR_MODEL = "mistral-ocr-latest"


def get_client() -> "Mistral":
    api_key = os.getenv("MISTRAL_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("Defina MISTRAL_API_KEY (ou API_KEY) no ambiente/.env.")
    return Mistral(api_key=api_key)
