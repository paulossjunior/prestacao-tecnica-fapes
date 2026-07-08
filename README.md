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
