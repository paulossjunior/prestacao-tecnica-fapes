"""Converte o relatório HTML em PDF usando um navegador headless (Chrome/Chromium).

Sem dependência Python extra: usa o navegador já instalado, que respeita o
CSS @media print do relatório. Detecta o executável automaticamente.
"""
import os
import shutil
import subprocess
import tempfile

# Caminhos comuns (macOS) + nomes no PATH (Linux).
_CANDIDATOS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
_NO_PATH = ["google-chrome", "google-chrome-stable", "chromium",
            "chromium-browser", "microsoft-edge"]


def _achar_navegador() -> str:
    env = os.getenv("CHROME_BIN")
    if env and os.path.exists(env):
        return env
    for c in _CANDIDATOS:
        if os.path.exists(c):
            return c
    for nome in _NO_PATH:
        achado = shutil.which(nome)
        if achado:
            return achado
    raise RuntimeError(
        "Navegador headless não encontrado. Instale o Google Chrome/Chromium "
        "ou defina CHROME_BIN com o caminho do executável."
    )


def html_para_pdf(html: str, out_pdf: str) -> str:
    """Renderiza uma string HTML em PDF (A4) e salva em out_pdf."""
    navegador = _achar_navegador()
    out_pdf = os.path.abspath(out_pdf)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = os.path.join(tmp, "parecer.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = [
            navegador, "--headless", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out_pdf}",
            f"--crash-dumps-dir={tmp}",
            f"file://{html_path}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not os.path.exists(out_pdf) or os.path.getsize(out_pdf) == 0:
        raise RuntimeError(f"Falha ao gerar PDF via {navegador}: {proc.stderr[:500]}")
    return out_pdf
