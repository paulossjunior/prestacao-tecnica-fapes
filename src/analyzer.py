"""Chamada ao Mistral para produzir a análise em JSON."""
import json

from mistral_client import MODEL, get_client
from prompts import build_user_prompt, get_system_prompt


def analisar(projeto_texto: str, prestacao_texto: str, client=None) -> dict:
    """Envia os documentos ao modelo e retorna a análise como dict."""
    client = client or get_client()
    resp = client.chat.complete(
        model=MODEL,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": build_user_prompt(projeto_texto, prestacao_texto)},
        ],
    )
    conteudo = resp.choices[0].message.content
    try:
        return json.loads(conteudo)
    except json.JSONDecodeError as e:
        raise ValueError(f"Modelo não retornou JSON válido: {e}\n\nResposta:\n{conteudo}")
