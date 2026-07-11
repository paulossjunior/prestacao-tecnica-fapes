# Avaliação Técnica de Prestação de Contas (POC)

POC em Python + web que compara o **previsto** (documento de projeto: objetivos,
indicadores, plano de trabalho, entregáveis) com o **realizado** (prestação de
contas técnica) e emite um **parecer estruturado** + **relatório HTML**, usando a
API da **Mistral**. Contexto: FAPES/IFES.

## Estrutura

```
.
├── run.py                 # entrypoint web (python run.py)
├── requirements.txt
├── .env.example
├── documentos/
│   ├── projeto/           # PDFs/docx do PROJETO enviado
│   └── prestacao/         # PDFs/docx da PRESTAÇÃO (evidências)
└── src/
    ├── app.py             # servidor Flask + rotas (/analisar, /relatorio)
    ├── cli.py             # execução por terminal (lê as pastas acima)
    ├── analyzer.py        # análise: docs -> JSON (chat, JSON mode)
    ├── report.py          # JSON -> parecer HTML (via Mistral)
    ├── extract.py         # extração local de texto (pypdf/docx)
    ├── mistral_ocr.py     # extração via OCR NATIVO da Mistral (PDF -> markdown)
    ├── mistral_client.py  # fábrica de cliente (compat SDK v1/v2)
    ├── prompts.py         # system prompts (análise + relatório)
    └── templates/index.html
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edite: MISTRAL_API_KEY=...
```

## Modo 1 — Terminal (pastas)

Coloque os arquivos em `documentos/projeto/` e `documentos/prestacao/`.

```bash
# análise + JSON + relatório HTML + PDF, extração local (pypdf)
python src/cli.py --out parecer.json --html parecer.html --pdf parecer.pdf

# usando o OCR NATIVO da Mistral (melhor p/ PDF escaneado / tabelas)
python src/cli.py --ocr --out parecer.json --html parecer.html --pdf parecer.pdf

# pastas customizadas
python src/cli.py caminho/projeto caminho/prestacao --pdf parecer.pdf
```

Opções: `--ocr` (OCR Mistral), `--out ARQ.json`, `--html ARQ.html`, `--pdf ARQ.pdf`.

O PDF é gerado por navegador headless (Chrome/Chromium/Edge), respeitando o CSS
de impressão. Defina `CHROME_BIN` se o executável não for detectado.

## Modo 2 — Web

```bash
python run.py            # http://127.0.0.1:5000
```

1. Envie os arquivos do **Projeto** e da **Prestação** (múltiplos, arrastar).
2. **Analisar** → parecer estruturado na tela.
3. **Gerar relatório HTML** → parecer formatado abre em nova aba (imprimir/PDF).

Formatos: `.pdf`, `.docx`, `.txt`, `.md`.

## Duas formas de ler PDF

- **Local (`extract.py`, padrão)**: rápido, sem custo extra; usa a camada de texto
  do PDF. Não lê PDF escaneado (imagem).
- **OCR Mistral (`--ocr` / `mistral_ocr.py`)**: envia o PDF à Mistral (upload →
  signed URL → `ocr.process`), retorna markdown com **tabelas preservadas**. Lê
  PDF escaneado. Tem custo/latência por página.

## Saída

- **JSON**: resumo executivo, grau de conformidade (0-100), entregáveis
  (ATENDIDO/PARCIAL/NÃO ATENDIDO/NÃO EVIDENCIADO), indicadores, cronograma,
  pontos de melhoria, pendências críticas, **parecer**
  (APROVAR / APROVAR COM RESSALVAS / DILIGÊNCIA / REPROVAR).
- **HTML**: parecer técnico institucional, autocontido, pronto p/ impressão (A4).

## Modo 3 — Docker Compose (recomendado)

Roda a aplicação web isolada em container, sem instalar Python/deps na máquina.

### Pré-requisitos
- Docker Desktop (ou Docker Engine) com o daemon **rodando**.
- Uma chave da API Mistral.

### Passo a passo

```bash
# 1) chave de API
cp .env.example .env
#    edite .env e preencha: MISTRAL_API_KEY=sua_chave

# 2) sobe (build + start em background)
docker compose up -d --build

# 3) acesse
open http://localhost:8080        # ou abra no navegador

# 4) logs / parar
docker compose logs -f web        # acompanhar em tempo real
docker compose down               # parar e remover o container
```

Primeiro build leva ~1-2 min (baixa a imagem base e instala deps). Subidas
seguintes são instantâneas (`docker compose up -d`, sem `--build`).

### Verificar se está no ar

```bash
curl -o /dev/null -w "%{http_code}\n" http://localhost:8080/            # 200
curl -o /dev/null -w "%{http_code}\n" http://localhost:8080/static/logo.png  # 200
docker compose ps                                                        # STATUS = Up
```

### Testar a análise pela linha de comando (opcional)

O endpoint é assíncrono: envia os arquivos e retorna um `job_id`; consulte o
resultado em `/status/<job_id>`.

```bash
# 1) enfileira o job (retorna job_id na hora)
curl -s -X POST http://localhost:8080/analisar \
  -F "projeto=@exemplos/projeto.txt" \
  -F "prestacao=@exemplos/prestacao.txt" \
  -F "prestacao=@exemplos/prestacao2.txt"
# -> {"job_id":"<id>","status":"processing"}

# 2) consulte o status até "done" (leva ~30-60s)
curl -s http://localhost:8080/status/<id>
# -> {"status":"done","resultado":{ ...parecer JSON... }}
```

Pela **web** (recomendado): abra http://localhost:8080, clique **+ Adicionar
arquivos** em cada seção (Projeto e Prestação; aceita vários), **Analisar** e
depois **Gerar relatório HTML**.

### Como funciona o container
- `Dockerfile`: `python:3.12-slim`, instala `requirements.txt`, roda
  `gunicorn wsgi:app` (1 worker, 4 threads, timeout 600s).
- `docker-compose.yml`: mapeia **host 8080 → container 8000**, lê o `.env` e
  passa **apenas** `MISTRAL_API_KEY` e `MISTRAL_MODEL` (o resto do `.env` não
  entra no container), `restart: unless-stopped`.
- A análise roda em thread (assíncrona) → a conexão HTTP nunca fica presa.

### Solução de problemas
| Sintoma | Causa / correção |
|---------|------------------|
| `Cannot connect to the Docker daemon` | Docker Desktop parado. Abra-o e aguarde o daemon subir. |
| `bind: address already in use` (8080) | Outra coisa usa a 8080. Troque a porta host em `docker-compose.yml` (ex.: `"8090:8000"`). |
| `defina MISTRAL_API_KEY no .env` | `.env` ausente ou sem a chave. Crie a partir de `.env.example`. |
| Erro "Job não encontrado" no front | Container reiniciou no meio da análise (job store é em memória). Reenvie. |
| PDF | O container não tem navegador headless; use "Imprimir → Salvar como PDF" no navegador. O `--pdf` do CLI só funciona fora do container. |

> Porta **8080** foi escolhida porque no macOS a **5000** costuma estar ocupada
> pelo *AirPlay Receiver*.

## Deploy no Render (teste)

O projeto já vem com `render.yaml` (Blueprint) + `wsgi.py` (gunicorn).

1. Push do repositório no GitHub (já feito).
2. Render → **New** → **Blueprint** → conecte o repo
   `paulossjunior/prestacao-tecnica-fapes`. O Render lê o `render.yaml`.
3. Em **Environment**, defina o secret **`MISTRAL_API_KEY`** (não vai no git).
4. **Create** → build (`pip install`) + start
   (`gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 180`).
5. Acesse a URL pública `https://<seu-serviço>.onrender.com`.

Deploy rápido:
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/paulossjunior/prestacao-tecnica-fapes)

Observações:
- Plano **free** hiberna após inatividade (primeiro acesso demora ~30-60s).
- `--timeout 180`: a análise via Mistral leva ~30-60s; timeout curto derruba a requisição.
- **PDF**: no Render não há navegador headless; o `--pdf` do CLI não roda lá. Na web,
  gere o **relatório HTML** e use "Imprimir → Salvar como PDF" do navegador.

## Configuração (`.env`)

| Var | Padrão | Uso |
|-----|--------|-----|
| `MISTRAL_API_KEY` | — | obrigatória |
| `MISTRAL_MODEL` | `mistral-large-latest` | análise + relatório |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | OCR nativo |
| `PORT` | `5000` | porta web |

## Notas

- O modelo é instruído a se basear **apenas** no conteúdo dos documentos.
- Texto de cada arquivo é truncado em ~120k caracteres (`MAX_CHARS` em `extract.py`).
- POC: sem persistência, sem autenticação. Não usar em produção como está.
```
