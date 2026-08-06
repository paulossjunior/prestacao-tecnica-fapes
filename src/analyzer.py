"""Chamada ao LLM (Mistral ou OpenAI) para produzir a análise em JSON."""
from llm import get_llm
from prompts import build_user_prompt, get_system_prompt


def analisar(projeto_texto: str, prestacao_texto: str, llm=None,
             system_prompt: str | None = None, perfil: str | None = None) -> dict:
    """Envia os documentos ao modelo e retorna a análise como dict.

    `perfil` escolhe os critérios do tipo de projeto (.agents/perfis/*.md).
    `system_prompt` sobrepõe tudo (usado pela aba "Prompt" da web); vazio ou
    ausente = prompt padrão do perfil + skill de escrita.
    """
    llm = llm or get_llm()
    return llm.chat_json(
        (system_prompt or "").strip() or get_system_prompt(perfil),
        build_user_prompt(projeto_texto, prestacao_texto),
    )
