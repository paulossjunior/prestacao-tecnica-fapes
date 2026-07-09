"""Entrypoint: python run.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from app import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    # threaded=True: análise longa (~1-3 min) não bloqueia o resto da UI.
    # use_reloader=False: evita que salvar arquivos derrube requisições em andamento.
    app.run(host="127.0.0.1", port=port, debug=True,
            threaded=True, use_reloader=False)
