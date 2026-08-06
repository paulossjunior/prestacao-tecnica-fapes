"""Fábrica de cliente OpenAI (compatível com gateways via OPENAI_BASE_URL)."""
import os

from openai import OpenAI

DEFAULT_MODEL = "gpt-4o"


def get_client() -> "OpenAI":
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY (ou API_KEY) no ambiente/.env.")
    # BASE_URL opcional: Azure OpenAI, OpenRouter, proxies compatíveis.
    return OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
