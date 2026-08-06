"""Transcrição de PDF usando o OCR nativo da Mistral.

Fluxo por arquivo: upload (purpose="ocr") -> signed URL -> ocr.process ->
concatena o markdown das páginas. Melhor que pypdf para PDFs escaneados,
com tabelas ou layout complexo.
"""
import os


def ocr_pdf(client, path: str, model: str) -> str:
    """Roda o OCR da Mistral em um único PDF e retorna o markdown das páginas."""
    with open(path, "rb") as f:
        conteudo = f.read()

    enviado = client.files.upload(
        file={"file_name": os.path.basename(path), "content": conteudo},
        purpose="ocr",
    )
    try:
        signed = client.files.get_signed_url(file_id=enviado.id)
        resp = client.ocr.process(
            model=model,
            document={"type": "document_url", "document_url": signed.url},
        )
    finally:
        # Não deixa lixo na conta; ignora falha de limpeza.
        try:
            client.files.delete(file_id=enviado.id)
        except Exception:
            pass

    paginas = [p.markdown for p in resp.pages if getattr(p, "markdown", "")]
    return "\n\n".join(paginas).strip()
