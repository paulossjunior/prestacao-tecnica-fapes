# Avaliação Técnica de Prestação de Contas (POC)

POC em Python + web que compara o **previsto** (documento de projeto: objetivos,
indicadores, plano de trabalho, entregáveis) com o **realizado** (prestação de
contas técnica) e emite um **parecer estruturado** + **relatório HTML**, usando a
API da **OpenAI** ou da **Mistral** (escolha por variável de ambiente).
Contexto: FAPES/IFES.

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
    ├── report.py          # JSON -> parecer HTML (render local, sem LLM)
    ├── extract.py         # extração local de texto (pypdf/docx)
    ├── llm.py             # camada de provedor: OpenAI ou Mistral (chat + OCR)
    ├── ocr.py             # OCR de pasta usando o provedor ativo
    ├── openai_client.py   # fábrica de cliente OpenAI
    ├── openai_ocr.py      # PDF -> markdown via Responses API (visão)
    ├── mistral_client.py  # fábrica de cliente Mistral (compat SDK v1/v2)
    ├── mistral_ocr.py     # PDF -> markdown via OCR NATIVO da Mistral
    ├── prompts.py         # system prompts (análise + relatório)
    └── templates/index.html
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edite: API_KEY=... e MODEL=...
```

## Provedor de LLM (OpenAI ou Mistral)

Forma simples — chave e modelo genéricos; o provedor é deduzido do nome do modelo:

```bash
API_KEY=sk-proj-...    MODEL=gpt-4o                 # -> OpenAI
API_KEY=...            MODEL=mistral-large-latest   # -> Mistral
```

Forma explícita (vence a dedução) — útil quando as duas chaves coexistem:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o
```

Ordem de resolução do provedor: `LLM_PROVIDER` → chave específica presente
(`OPENAI_API_KEY`/`MISTRAL_API_KEY`) → prefixo do nome do modelo → prefixo da
`API_KEY` (`sk-` = OpenAI). Modelo incompatível com o provedor ativo (ex.:
`gpt-4o` com `LLM_PROVIDER=mistral`) falha na inicialização com mensagem clara.

No CLI, `--provider openai|mistral` sobrepõe o ambiente para aquela execução.

## Modo 1 — Terminal (pastas)

Coloque os arquivos em `documentos/projeto/` e `documentos/prestacao/`.

```bash
# análise + JSON + relatório HTML + PDF, extração local (pypdf)
python src/cli.py --out parecer.json --html parecer.html --pdf parecer.pdf

# usando OCR/visão do provedor (melhor p/ PDF escaneado / tabelas)
python src/cli.py --ocr --out parecer.json --html parecer.html --pdf parecer.pdf

# forçando o provedor nesta execução
python src/cli.py --provider openai --out parecer.json --html parecer.html

# pastas customizadas
python src/cli.py caminho/projeto caminho/prestacao --pdf parecer.pdf
```

Opções: `--ocr`, `--perfil pesquisa|inovacao|extensao`,
`--provider openai|mistral`, `--out ARQ.json`, `--html ARQ.html`, `--pdf ARQ.pdf`.

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

### Perfis por tipo de projeto

O dropdown **Tipo de projeto** (aba Documentos) escolhe os critérios de
avaliação. A escolha é manual — não há detecção automática.

| Perfil | Ênfase |
|--------|--------|
| Padrão | avaliação genérica, sem ênfase por tipo |
| Pesquisa | produção científica, formação de RH, método, infraestrutura |
| Inovação | artefato entregue, validação técnica, PI, transferência |
| Extensão | público atendido, ações realizadas, capacitação, difusão |

O perfil muda **prioridades, evidências aceitas e calibração do parecer**;
o **schema JSON não muda**, então tela e relatório funcionam igual nos quatro.

Cada perfil é um arquivo em `.agents/perfis/<id>.md` — criar um tipo novo é
soltar um `.md` na pasta; o dropdown e o CLI o listam sozinhos. Convenção:
`# Nome` na primeira linha, descrição curta na linha seguinte, critérios no
resto. No terminal: `python src/cli.py --perfil pesquisa`.

### Aba "Prompt do sistema"

A tela tem duas abas: **Documentos** e **Prompt do sistema**. A segunda mostra o
prompt exato enviado ao modelo (schema JSON + regras + a skill de escrita de
`.agents/AGENTS.md`), editável antes de clicar em **Analisar**.

- O texto carrega de `GET /prompt` e vai junto no `POST /analisar`
  (campo `system_prompt`). Campo vazio → o servidor usa o padrão.
- **↺ Restaurar padrão** volta ao original; um ponto rosa na aba sinaliza
  prompt personalizado.
- A edição vale só para aquela análise — não altera o código nem o `.agents/`.
- Deep link: `http://localhost:5000/?aba=prompt` abre já nessa aba.

> As chaves do JSON (`entregaveis`, `indicadores`, `parecer`…) alimentam a tela e
> o relatório. Mudar as **regras** e os critérios é seguro; remover chaves do
> **schema** deixa seções vazias. Para mudar só o estilo da escrita, edite
> `.agents/AGENTS.md` — vale para todas as análises, sem tocar no prompt.

## Duas formas de ler PDF

- **Local (`extract.py`, padrão)**: rápido, sem custo extra; usa a camada de texto
  do PDF. Não lê PDF escaneado (imagem).
- **OCR do provedor (`--ocr`)**: lê PDF escaneado e preserva tabelas em markdown;
  tem custo/latência por página.
  - **Mistral** (`mistral_ocr.py`): OCR nativo — upload → signed URL →
    `ocr.process`.
  - **OpenAI** (`openai_ocr.py`): sem endpoint de OCR dedicado; o PDF vai inline
    (base64) para a Responses API e o modelo multimodal transcreve. Limites da
    API: ~32 MB e ~100 páginas por arquivo.

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
- Uma chave da API OpenAI ou Mistral.

### Passo a passo

```bash
# 1) chave de API
cp .env.example .env
#    edite .env e preencha: API_KEY=sua_chave e MODEL=gpt-4o (ou mistral-large-latest)

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
- `docker-compose.yml`: mapeia **host 8080 → container 8000**, carrega o `.env`
  inteiro no container (`env_file`) e define fallbacks de `LLM_PROVIDER`,
  `MISTRAL_MODEL` e `OPENAI_MODEL`, `restart: unless-stopped`.
- A análise roda em thread (assíncrona) → a conexão HTTP nunca fica presa.

### Solução de problemas
| Sintoma | Causa / correção |
|---------|------------------|
| `Cannot connect to the Docker daemon` | Docker Desktop parado. Abra-o e aguarde o daemon subir. |
| `bind: address already in use` (8080) | Outra coisa usa a 8080. Troque a porta host em `docker-compose.yml` (ex.: `"8090:8000"`). |
| `Defina OPENAI_API_KEY (ou API_KEY)` / idem Mistral | `.env` ausente ou sem a chave. Crie a partir de `.env.example`. |
| `Modelo 'X' é do provedor 'Y'...` | `MODEL` não bate com o provedor ativo. Ajuste `MODEL` ou `LLM_PROVIDER`. |
| Erro "Job não encontrado" no front | Container reiniciou no meio da análise (job store é em memória). Reenvie. |
| PDF | O container não tem navegador headless; use "Imprimir → Salvar como PDF" no navegador. O `--pdf` do CLI só funciona fora do container. |

> Porta **8080** foi escolhida porque no macOS a **5000** costuma estar ocupada
> pelo *AirPlay Receiver*.

## Deploy no Render (teste)

O projeto já vem com `render.yaml` (Blueprint) + `wsgi.py` (gunicorn).

1. Push do repositório no GitHub (já feito).
2. Render → **New** → **Blueprint** → conecte o repo
   `paulossjunior/prestacao-tecnica-fapes`. O Render lê o `render.yaml`.
3. Em **Environment**, defina o secret da API (**`OPENAI_API_KEY`** ou
   **`MISTRAL_API_KEY`**; não vai no git) e ajuste `LLM_PROVIDER`.
4. **Create** → build (`pip install`) + start
   (`gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 180`).
5. Acesse a URL pública `https://<seu-serviço>.onrender.com`.

Deploy rápido:
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/paulossjunior/prestacao-tecnica-fapes)

Observações:
- Plano **free** hiberna após inatividade (primeiro acesso demora ~30-60s).
- `--timeout 180`: a análise leva ~30-60s; timeout curto derruba a requisição.
- **PDF**: no Render não há navegador headless; o `--pdf` do CLI não roda lá. Na web,
  gere o **relatório HTML** e use "Imprimir → Salvar como PDF" do navegador.

## Configuração (`.env`)

| Var | Padrão | Uso |
|-----|--------|-----|
| `API_KEY` | — | chave genérica; usada se a específica do provedor não existir |
| `MODEL` | — | modelo genérico; também serve para deduzir o provedor |
| `LLM_PROVIDER` | dedução | `openai` \| `mistral`; explícito, vence a dedução |
| `OPENAI_API_KEY` | — | obrigatória com provedor `openai` (ou use `API_KEY`) |
| `OPENAI_MODEL` | `gpt-4o` | análise |
| `OPENAI_OCR_MODEL` | = `OPENAI_MODEL` | transcrição de PDF (visão) |
| `OPENAI_BASE_URL` | — | endpoint compatível (Azure, proxy, gateway) |
| `MISTRAL_API_KEY` | — | obrigatória com provedor `mistral` (ou use `API_KEY`) |
| `MISTRAL_MODEL` | `mistral-large-latest` | análise |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | OCR nativo |
| `PORT` | `5000` | porta web |

## Notas

- O modelo é instruído a se basear **apenas** no conteúdo dos documentos.
- Texto de cada arquivo é truncado em ~120k caracteres (`MAX_CHARS` em `extract.py`).
- POC: sem persistência, sem autenticação. Não usar em produção como está.
```
