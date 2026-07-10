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

EXPOSE 8000

# threaded + timeout alto: a análise via Mistral pode levar minutos.
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "600"]
