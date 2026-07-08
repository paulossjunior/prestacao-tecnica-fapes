"""Entrypoint WSGI para produção (gunicorn wsgi:app)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from app import app  # noqa: E402

# gunicorn procura o objeto `app`. Local: `python run.py`.
