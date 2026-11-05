"""Transcrição de PDF via OpenAI (Responses API, PDF enviado inline em base64).

A OpenAI não tem endpoint de OCR dedicado: o modelo multimodal recebe o PDF
inteiro (texto + páginas renderizadas) e devolve markdown. Limites da API:
~32 MB e ~100 páginas por arquivo.
"""
import base64
import os

# Enquadrar como "extrair texto visível" (não "transcrever integralmente")
# evita a recusa do modelo com documentos oficiais escaneados. Frases extras
# como "não invente/devolva apenas o texto" reativam a recusa — manter enxuto.
_PROMPT = (
    "Extraia e liste em Markdown todo o texto visível nas páginas deste "
    "documento (relatório técnico de projeto). Inclua títulos, parágrafos e "
    "tabelas na ordem das páginas."
)


def ocr_pdf(client, path: str, model: str) -> str:
    """Roda a transcrição em um único PDF e retorna o markdown."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    resp = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {
                    "type": "input_file",
                    "filename": os.path.basename(path),
                    "file_data": f"data:application/pdf;base64,{b64}",
                },
                {"type": "input_text", "text": _PROMPT},
            ],
        }],
    )
    return (resp.output_text or "").strip()


def ocr_image(client, path: str, model: str, mime: str = "image/png") -> str:
    """Transcreve uma IMAGEM (JPEG/PNG/…) via visão do modelo. Usado quando um
    anexo chega como imagem (às vezes com extensão .pdf trocada)."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    resp = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                {"type": "input_text", "text": _PROMPT},
            ],
        }],
    )
    return (resp.output_text or "").strip()
