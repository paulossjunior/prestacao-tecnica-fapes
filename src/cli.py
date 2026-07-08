"""Avaliação técnica via terminal, lendo PDFs (e docx/txt/md) de pastas.

Uso:
    python src/cli.py [pasta_projeto] [pasta_prestacao] [opções]

Padrão (sem argumentos):
    pasta_projeto   = documentos/projeto
    pasta_prestacao = documentos/prestacao

Opções:
    --ocr            usa o OCR nativo da Mistral nos PDFs (melhor p/ escaneados)
    --out ARQ.json   salva o JSON da análise
    --html ARQ.html  gera o parecer técnico executivo em HTML e salva
    --pdf ARQ.pdf    gera o parecer em PDF (via navegador headless)

Ex.:
    python src/cli.py
    python src/cli.py --ocr --out parecer.json --html parecer.html --pdf parecer.pdf
"""
import json
import sys

from dotenv import load_dotenv

from analyzer import analisar
from extract import extract_folder
from mistral_client import get_client
from report import gerar_html

load_dotenv()

PROJETO_PADRAO = "documentos/projeto"
PRESTACAO_PADRAO = "documentos/prestacao"


def _opt_valor(raw, flag):
    """Extrai o valor de uma opção "--flag valor" e remove ambos de `raw`."""
    if flag in raw:
        i = raw.index(flag)
        valor = raw[i + 1] if i + 1 < len(raw) else None
        del raw[i:i + 2]
        return valor
    return None


def main() -> int:
    raw = sys.argv[1:]
    usar_ocr = False
    if "--ocr" in raw:
        usar_ocr = True
        raw.remove("--ocr")
    out_json = _opt_valor(raw, "--out")
    out_html = _opt_valor(raw, "--html")
    out_pdf = _opt_valor(raw, "--pdf")
    args = [a for a in raw if not a.startswith("--")]

    pasta_projeto = args[0] if len(args) >= 1 else PROJETO_PADRAO
    pasta_prestacao = args[1] if len(args) >= 2 else PRESTACAO_PADRAO

    log = lambda m: print(m, file=sys.stderr)
    log(f"[projeto]   {pasta_projeto}")
    log(f"[prestacao] {pasta_prestacao}")
    log(f"[extração]  {'Mistral OCR' if usar_ocr else 'local (pypdf)'}")

    client = get_client()

    if usar_ocr:
        from mistral_ocr import ocr_folder
        projeto = ocr_folder(pasta_projeto, client)
        prestacao = ocr_folder(pasta_prestacao, client)
    else:
        projeto = extract_folder(pasta_projeto)
        prestacao = extract_folder(pasta_prestacao)
    log(f"[extraído]  projeto={len(projeto)} chars, prestacao={len(prestacao)} chars")

    log("[analisando via Mistral...]")
    resultado = analisar(projeto, prestacao, client)
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)

    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            f.write(texto)
        log(f"[salvo] {out_json}")

    html = None
    if out_html or out_pdf:
        log("[gerando relatório HTML executivo...]")
        html = gerar_html(resultado)

    if out_html:
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"[salvo] {out_html}")

    if out_pdf:
        from pdf import html_para_pdf
        log("[gerando PDF via navegador headless...]")
        html_para_pdf(html, out_pdf)
        log(f"[salvo] {out_pdf}")

    if not any((out_json, out_html, out_pdf)):
        print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
