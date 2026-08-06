"""Chamada ao LLM (Mistral ou OpenAI) para produzir a análise em JSON."""
from llm import get_llm
from prompts import build_user_prompt, get_system_prompt


def analisar(projeto_texto: str, prestacao_texto: str, llm=None,
             system_prompt: str | None = None) -> dict:
    """Envia os documentos ao modelo e retorna a análise como dict.

    `system_prompt` sobrepõe o prompt padrão (usado pela aba "Prompt" da web).
    Vazio/ausente = prompt padrão + skill de escrita (.agents/AGENTS.md).
    """
    llm = llm or get_llm()
    return llm.chat_json(
        (system_prompt or "").strip() or get_system_prompt(),
        build_user_prompt(projeto_texto, prestacao_texto),
    )
