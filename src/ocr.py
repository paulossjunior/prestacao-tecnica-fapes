"""Extração de pasta via OCR do provedor ativo (Mistral ou OpenAI).

Mesma saída de `extract.extract_folder`, mas PDFs passam pelo OCR/visão do LLM.
Arquivos não-PDF continuam no extrator local.
"""
import os

from extract import SUPORTADOS, extract_file
from llm import get_llm


def ocr_folder(dirpath: str, llm=None) -> str:
    """Concatena o texto de todos os documentos da pasta, PDFs via OCR do LLM."""
    if not os.path.isdir(dirpath):
        raise ValueError(f"Pasta não encontrada: {dirpath}")
    llm = llm or get_llm()

    caminhos = []
    for raiz, _, arquivos in os.walk(dirpath):
        for nome in sorted(arquivos):
            if nome.startswith(".") or nome.startswith("~$"):
                continue  # ocultos / lock temporário do Office
            if os.path.splitext(nome)[1].lower() in SUPORTADOS:
                caminhos.append(os.path.join(raiz, nome))
    if not caminhos:
        raise ValueError(f"Nenhum documento suportado em {dirpath} (pdf/docx/txt/md).")

    blocos = []
    for caminho in sorted(caminhos):
        rel = os.path.relpath(caminho, dirpath)
        if caminho.lower().endswith(".pdf"):
            texto = llm.ocr_pdf(caminho)
        else:
            texto = extract_file(caminho)
        blocos.append(f"--- ARQUIVO: {rel} ---\n{texto}")
    return "\n\n".join(blocos)
