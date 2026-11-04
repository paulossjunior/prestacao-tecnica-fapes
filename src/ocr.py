"""Extração de pasta via OCR do provedor ativo (Mistral ou OpenAI).

Mesma saída de `extract.extract_folder`, mas PDFs passam pelo OCR/visão do LLM.
Arquivos não-PDF continuam no extrator local.
"""
import os

from extract import MAX_CHARS, SUPORTADOS, _from_pdf, extract_file
from llm import get_llm

# Abaixo deste nº de caracteres, um PDF é tratado como escaneado (sem camada de
# texto) e enviado ao OCR do provedor.
MIN_CHARS_PDF = 100


def _truncar(texto: str) -> str:
    texto = texto.strip()
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS] + "\n\n[...documento truncado...]"
    return texto


def pdf_escaneado(path: str) -> bool:
    """True se o PDF não tem camada de texto útil (precisa de OCR)."""
    if not path.lower().endswith(".pdf"):
        return False
    try:
        with open(path, "rb") as f:
            return len(_from_pdf(f.read()).strip()) < MIN_CHARS_PDF
    except Exception:  # noqa: BLE001 — PDF corrompido/ilegível também vai p/ OCR
        return True


def extract_file_auto(path: str, llm=None, _ocr_cb=None) -> str:
    """Extrai texto de um arquivo. PDF escaneado cai automaticamente no OCR do LLM;
    PDF com texto e demais formatos usam o extrator local (rápido, sem custo)."""
    if path.lower().endswith(".pdf") and pdf_escaneado(path):
        llm = llm or get_llm()
        if _ocr_cb:
            _ocr_cb(path)
        return _truncar(llm.ocr_pdf(path))
    return extract_file(path)


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


def extract_folder_auto(dirpath: str, llm=None) -> str:
    """Como extract.extract_folder, mas detecta PDFs escaneados por arquivo e
    passa só eles pelo OCR do LLM (o resto continua na extração local)."""
    if not os.path.isdir(dirpath):
        raise ValueError(f"Pasta não encontrada: {dirpath}")
    caminhos = []
    for raiz, _, arquivos in os.walk(dirpath):
        for nome in sorted(arquivos):
            if nome.startswith(".") or nome.startswith("~$"):
                continue
            if os.path.splitext(nome)[1].lower() in SUPORTADOS:
                caminhos.append(os.path.join(raiz, nome))
    if not caminhos:
        raise ValueError(f"Nenhum documento suportado em {dirpath} (pdf/docx/txt/md).")

    def _aviso(p):
        print(f"[OCR] {os.path.basename(p)} escaneado — aplicando OCR.", flush=True)

    blocos = []
    for caminho in sorted(caminhos):
        rel = os.path.relpath(caminho, dirpath)
        texto = extract_file_auto(caminho, llm=llm, _ocr_cb=_aviso)
        blocos.append(f"--- ARQUIVO: {rel} ---\n{texto}")
    return "\n\n".join(blocos)
