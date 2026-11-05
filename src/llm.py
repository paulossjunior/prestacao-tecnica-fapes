"""Camada de LLM independente de provedor: Mistral ou OpenAI.

Configuração (do mais específico para o mais genérico):

    LLM_PROVIDER=mistral|openai      escolha explícita (vence tudo)
    OPENAI_API_KEY / MISTRAL_API_KEY chave por provedor
    OPENAI_MODEL   / MISTRAL_MODEL   modelo por provedor
    API_KEY / MODEL                  genéricos: valem para o provedor ativo

Sem `LLM_PROVIDER`, o provedor é deduzido do que estiver no ambiente: chave
específica presente, senão o nome do modelo, senão o prefixo da chave.

Toda leitura de env acontece em `get_llm()` (não no import), para funcionar
mesmo quando `load_dotenv()` roda depois dos imports.
"""
import json
import os

PROVIDERS = ("mistral", "openai")

# Prefixos de nome de modelo que identificam o provedor.
_PREFIXOS = {
    "openai": ("gpt", "o1", "o3", "o4", "chatgpt", "text-embedding", "davinci"),
    "mistral": ("mistral", "ministral", "magistral", "codestral", "pixtral",
                "devstral", "open-mistral", "open-mixtral"),
}


def _hint_modelo(nome: str) -> str | None:
    """Deduz o provedor pelo nome do modelo. None se não reconhecer."""
    nome = (nome or "").strip().lower()
    for provider, prefixos in _PREFIXOS.items():
        if nome.startswith(prefixos):
            return provider
    return None


def escolher_provedor() -> str:
    """Provedor efetivo: LLM_PROVIDER, senão dedução pelo ambiente."""
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if p:
        if p not in PROVIDERS:
            raise RuntimeError(
                f"LLM_PROVIDER inválido: {p!r}. Use 'mistral' ou 'openai'."
            )
        return p

    tem_openai = bool(os.getenv("OPENAI_API_KEY"))
    tem_mistral = bool(os.getenv("MISTRAL_API_KEY"))
    if tem_openai != tem_mistral:                    # exatamente uma definida
        return "openai" if tem_openai else "mistral"

    por_modelo = (_hint_modelo(os.getenv("OPENAI_MODEL") or "")
                  or _hint_modelo(os.getenv("MISTRAL_MODEL") or "")
                  or _hint_modelo(os.getenv("MODEL") or ""))
    if por_modelo:
        return por_modelo

    if tem_mistral:                                  # ambas definidas: compat
        return "mistral"
    if (os.getenv("API_KEY") or "").startswith("sk-"):
        return "openai"
    if os.getenv("API_KEY"):
        return "mistral"

    raise RuntimeError(
        "Nenhuma chave encontrada. Defina API_KEY (ou MISTRAL_API_KEY / "
        "OPENAI_API_KEY) e, se quiser ser explícito, LLM_PROVIDER=mistral|openai."
    )


def _checar_coerencia(provider: str, model: str) -> None:
    """Erro claro quando modelo e provedor não combinam (ex.: gpt-4o + Mistral)."""
    hint = _hint_modelo(model)
    if hint and hint != provider:
        raise RuntimeError(
            f"Modelo {model!r} é do provedor {hint!r}, mas o provedor ativo é "
            f"{provider!r}. Ajuste MODEL/LLM_PROVIDER no .env."
        )


class LLM:
    """Fachada com a mesma API para os dois provedores: chat JSON + OCR de PDF."""

    def __init__(self, provider: str, raw, model: str, ocr_model: str):
        self.provider = provider
        self.raw = raw          # cliente nativo do SDK (Mistral / OpenAI)
        self.model = model
        self.ocr_model = ocr_model

    def __repr__(self) -> str:  # aparece nos logs do CLI
        return f"<LLM {self.provider} model={self.model} ocr={self.ocr_model}>"

    # ---- chat ----
    def chat_json(self, system: str, user: str, temperature: float = 0.1) -> dict:
        """Chama o modelo em modo JSON e devolve o dict já parseado."""
        if self.provider == "mistral":
            conteudo = self._mistral_chat(system, user, temperature)
        else:
            conteudo = self._openai_chat(system, user, temperature)
        try:
            return json.loads(conteudo)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(
                f"Modelo não retornou JSON válido: {e}\n\nResposta:\n{conteudo}"
            )

    def _mistral_chat(self, system, user, temperature) -> str:
        resp = self.raw.chat.complete(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def _openai_chat(self, system, user, temperature) -> str:
        kwargs = dict(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        try:
            resp = self.raw.chat.completions.create(temperature=temperature, **kwargs)
        except Exception as e:  # noqa: BLE001
            # Modelos de raciocínio (série o*/gpt-5) rejeitam temperature custom.
            if "temperature" not in str(e):
                raise
            resp = self.raw.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    # ---- OCR ----
    def ocr_pdf(self, path: str) -> str:
        """Transcreve um PDF para markdown usando o OCR/visão do provedor."""
        if self.provider == "mistral":
            from mistral_ocr import ocr_pdf
        else:
            from openai_ocr import ocr_pdf
        return ocr_pdf(self.raw, path, self.ocr_model)

    def ocr_image(self, path: str, mime: str | None = None) -> str:
        """Transcreve uma IMAGEM (JPEG/PNG/…) para markdown via visão do provedor."""
        if self.provider == "mistral":
            from mistral_ocr import ocr_image
        else:
            from openai_ocr import ocr_image
        return ocr_image(self.raw, path, self.ocr_model, mime=mime or "image/png")


def get_llm(provider: str | None = None) -> LLM:
    """Cria o cliente do provedor escolhido, lendo modelos do ambiente."""
    provider = (provider or escolher_provedor()).lower()

    if provider == "mistral":
        from mistral_client import DEFAULT_MODEL, DEFAULT_OCR_MODEL, get_client
        model = os.getenv("MISTRAL_MODEL") or os.getenv("MODEL") or DEFAULT_MODEL
        ocr_model = os.getenv("MISTRAL_OCR_MODEL") or DEFAULT_OCR_MODEL
        _checar_coerencia(provider, model)
        return LLM(provider, get_client(), model, ocr_model)

    if provider == "openai":
        from openai_client import DEFAULT_MODEL, get_client
        model = os.getenv("OPENAI_MODEL") or os.getenv("MODEL") or DEFAULT_MODEL
        # Sem endpoint de OCR dedicado: o próprio modelo (multimodal) lê o PDF.
        ocr_model = os.getenv("OPENAI_OCR_MODEL") or model
        _checar_coerencia(provider, model)
        return LLM(provider, get_client(), model, ocr_model)

    raise RuntimeError(f"Provedor desconhecido: {provider!r} (use 'mistral' ou 'openai').")
