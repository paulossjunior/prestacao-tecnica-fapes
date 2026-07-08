"""Extração de texto de PDFs usando o OCR nativo da Mistral.

Fluxo por arquivo: upload (purpose="ocr") -> signed URL -> ocr.process ->
concatena o markdown das páginas. Melhor que pypdf para PDFs escaneados,
com tabelas ou layout complexo. Arquivos não-PDF caem no extrator local.
"""
import os

from mistral_client import OCR_MODEL, get_client
from extract import SUPORTADOS, extract_file


def ocr_pdf(client, path: str) -> str:
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
            model=OCR_MODEL,
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


def ocr_folder(dirpath: str, client=None) -> str:
    """Como extract.extract_folder, mas PDFs passam pelo OCR da Mistral."""
    if not os.path.isdir(dirpath):
        raise ValueError(f"Pasta não encontrada: {dirpath}")
    client = client or get_client()

    caminhos = []
    for raiz, _, arquivos in os.walk(dirpath):
        for nome in sorted(arquivos):
            if nome.startswith(".") or nome.startswith("~$"):
                continue
            if os.path.splitext(nome)[1].lower() in SUPORTADOS:
                caminhos.append(os.path.join(raiz, nome))
    if not caminhos:
        raise ValueError(f"Nenhum documento suportado em {dirpath} (pdf/docx/txt/md).")

    blocos = []
    for caminho in sorted(caminhos):
        rel = os.path.relpath(caminho, dirpath)
        if caminho.lower().endswith(".pdf"):
            texto = ocr_pdf(client, caminho)
        else:
            texto = extract_file(caminho)
        blocos.append(f"--- ARQUIVO: {rel} ---\n{texto}")
    return "\n\n".join(blocos)
