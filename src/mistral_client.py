"""Fábrica única de cliente Mistral (compat SDK v1 e v2)."""
import os

try:
    from mistralai import Mistral  # SDK v1
except ImportError:
    from mistralai.client import Mistral  # SDK v2 (layout mudou)

MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")


def get_client() -> "Mistral":
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("Defina a variável de ambiente MISTRAL_API_KEY.")
    return Mistral(api_key=api_key)
