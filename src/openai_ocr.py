"""Transcrição de PDF via OpenAI (Responses API, PDF enviado inline em base64).

A OpenAI não tem endpoint de OCR dedicado: o modelo multimodal recebe o PDF
inteiro (texto + páginas renderizadas) e devolve markdown. Limites da API:
~32 MB e ~100 páginas por arquivo.
"""
import base64
import os

_PROMPT = (
    "Transcreva integralmente o conteúdo deste PDF em Markdown. "
    "Preserve tabelas (em formato Markdown), títulos, listas e a ordem das "
    "páginas. Não resuma, não comente e não invente conteúdo: devolva apenas "
    "o texto do documento."
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
