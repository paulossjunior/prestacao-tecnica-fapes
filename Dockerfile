FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Dependências primeiro (cache de camada)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY wsgi.py run.py ./
COPY src ./src
# Skill de escrita executiva injetada nos prompts (prompts.py lê ../.agents).
COPY .agents ./.agents

# Usuário não-root. /app precisa ser gravável: o app escreve avaliações, cache e
# config.json em runtime (efêmeros — monte um volume p/ persistir, veja abaixo).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/avaliacoes /app/cache \
    && chown -R appuser:appuser /app
USER appuser

# Persistência opcional: monte um volume em /app/avaliacoes (e /app/cache) p/ as
# avaliações sobreviverem a redeploys. Sem volume, somem ao recriar o container.
VOLUME ["/app/avaliacoes"]

# A plataforma (Dokploy/Dokku/Render) injeta $PORT; default 8000 se ausente.
EXPOSE 8000

# shell-form p/ expandir ${PORT}. threaded + timeout alto: análise leva minutos.
CMD gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 600
