# Instalação — Prestação de Contas Técnica (FAPES)

Aplicação Flask que lista as propostas do SIGFAPES e avalia por LLM o relatório
técnico (Anexo VI) de cada projeto, gerando pareceres em PDF.

> **Primeira vez?** Siga o passo a passo em [TUTORIAL.md](TUTORIAL.md) (do zero ao
> primeiro parecer). Este arquivo é a **referência** de instalação (todas as opções).

> A aplicação **acessa o SIGFAPES autenticado** (faz login com usuário/senha) e
> chama a **API da OpenAI** (ou Mistral). Precisa de rede até o SIGFAPES e de uma
> chave de LLM. Não há dado embutido: as propostas são sincronizadas em runtime.

---

## 1. Pré-requisitos

- **Docker** + **Docker Compose** (recomendado), ou Python 3.12 para rodar local.
- **Credenciais do SIGFAPES** (login e senha de um usuário com acesso às propostas).
- **Chave de API** da OpenAI (padrão) ou da Mistral.
- Rede com acesso a `https://www.sigfapes.es.gov.br` e à API do provedor de LLM.

---

## 2. Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `LLM_PROVIDER` | não | `openai` | `openai` ou `mistral`. |
| `OPENAI_API_KEY` | sim¹ | — | Chave da OpenAI (secret). |
| `OPENAI_MODEL` | não | `gpt-4o` | Modelo de análise. |
| `OPENAI_OCR_MODEL` | não | = `OPENAI_MODEL` | Modelo de OCR por visão (ex.: `gpt-5.4-nano`). |
| `MISTRAL_API_KEY` | sim¹ | — | Chave da Mistral (se `LLM_PROVIDER=mistral`). |
| `MISTRAL_MODEL` | não | `mistral-large-latest` | Modelo de análise (Mistral). |
| `SIGFAPES_USER` | sim | — | Login do SIGFAPES. **Use este nome, não `USER`** (ver nota²). |
| `SIGFAPES_PASSWORD` | sim | — | Senha do SIGFAPES. |
| `SIGFAPES_SITE` | não | `https://www.sigfapes.es.gov.br` | Base do SIGFAPES. |
| `AVAL_AMOSTRAS` | não | `3` | Nº de rodadas do LLM por documento; a nota é a **mediana**. `1` desliga (mais barato). |
| `PORT` | não | `8000` | Porta HTTP (a plataforma costuma injetar). |

¹ Uma das duas chaves, conforme o `LLM_PROVIDER`.
² Em containers, `USER` colide com o usuário do sistema operacional. O app lê
primeiro `SIGFAPES_USER`/`SIGFAPES_PASSWORD`/`SIGFAPES_SITE`; só caia em
`USER`/`PASSWORD`/`SITE` no desenvolvimento local via `.env`.

> **Segurança:** essas credenciais são de um sistema do governo e uma chave paga
> de LLM. Trate-as como segredos (nunca no git), e rotacione se vazarem. Ao subir
> em host de terceiros (Render, VPS), as credenciais saem para aquele host.

---

## 3. Instalar pela imagem do GitHub Packages (ghcr.io) — recomendado

A cada push na `main`, o CI **versiona automaticamente** (semver por Conventional
Commits: `feat`→minor, `fix`/`docs`/`chore`→patch, `BREAKING CHANGE`/`!`→major),
cria a tag + GitHub Release e publica a imagem em
`ghcr.io/paulossjunior/prestacao-tecnica-fapes` com as tags `latest`, `X.Y.Z` e `X.Y`.
Para fixar uma versão, troque `:latest` por `:X.Y.Z` (ex.: `:1.2.0`).

```bash
docker run -d --name prestacao -p 8080:8000 \
  -e LLM_PROVIDER=openai \
  -e OPENAI_API_KEY=sk-... \
  -e OPENAI_MODEL=gpt-4o \
  -e OPENAI_OCR_MODEL=gpt-5.4-nano \
  -e SIGFAPES_USER='seu_login' \
  -e SIGFAPES_PASSWORD='sua_senha' \
  -v prestacao_avaliacoes:/app/avaliacoes \
  -v prestacao_cache:/app/cache \
  ghcr.io/paulossjunior/prestacao-tecnica-fapes:latest
```

Acesse **http://localhost:8080**. Na primeira vez, clique em **Sincronizar** para
baixar as propostas (faz login no SIGFAPES). Os volumes persistem avaliações e o
cache de propostas entre atualizações.

Se o pacote for privado, autentique antes:
`echo $GHCR_TOKEN | docker login ghcr.io -u SEU_USER --password-stdin`
(token com escopo `read:packages`).

---

## 4. Instalar com Docker Compose (build local)

Clone o repositório, crie um `.env` e suba:

```bash
git clone https://github.com/paulossjunior/prestacao-tecnica-fapes.git
cd prestacao-tecnica-fapes
cp .env.example .env   # se não existir, crie com as variáveis da seção 2
docker compose up -d --build
```

O `docker-compose.yml` já mapeia `8080:8000`, carrega o `.env` e cria volumes
para `avaliacoes` e `cache`. Acesse **http://localhost:8080**.

---

## 5. Deploy no Dokploy

1. **New → Application** → conecte o repositório.
2. **Build Type: Dockerfile** (detectado automaticamente).
3. **Port do container:** `8000` (ou deixe o Dokploy injetar `$PORT`).
4. **Environment:** as variáveis da seção 2 (use `SIGFAPES_USER`/`SIGFAPES_PASSWORD`).
5. (Opcional) **Volume** em `/app/avaliacoes` (e `/app/cache`) para persistir.
6. **Deploy.**

---

## 6. Deploy no Render

O repositório traz um `render.yaml` (Blueprint):

1. **New → Blueprint** → conecte o repositório (lê o `render.yaml`).
2. Defina os segredos `OPENAI_API_KEY`, `SIGFAPES_USER`, `SIGFAPES_PASSWORD`.
3. **Apply.** URL: `https://prestacao-tecnica-fapes.onrender.com`.

> Plano free é **efêmero** (avaliações somem no redeploy/restart) e **dorme** após
> 15 min (1ª visita ~50 s). Para persistir, use plano pago com Disk em `/app/avaliacoes`.

---

## 7. Desenvolvimento local (sem Docker)

Requer Python 3.12 e um **Google Chrome/Chromium** instalado (o PDF do parecer é
renderizado por navegador headless; defina `CHROME_BIN` se não for autodetectado).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cat > .env <<'ENV'
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_OCR_MODEL=gpt-5.4-nano
USER=seu_login
PASSWORD=sua_senha
SITE=https://www.sigfapes.es.gov.br
ENV
PORT=8080 python run.py
```

`run.py` roda o servidor de desenvolvimento do Flask. Em produção use o
`wsgi:app` com gunicorn (como no Docker).

---

## 8. Persistência

O app grava em disco (efêmero no container sem volume):

- `avaliacoes/` — avaliações, pareceres e PDFs consolidados.
- `cache/` — `propostas.csv` (cache da sincronização).
- `config.json` — limiar de aprovação.

Monte volumes em `/app/avaliacoes` e `/app/cache` para não perder nada em
atualizações/reinícios.

---

## 9. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Lista de propostas vazia | Cache não sincronizado | Clique em **Sincronizar** (faz login no SIGFAPES). |
| Login falha / "Defina USER e PASSWORD" | Credenciais ausentes ou `USER` colidindo com o SO | Use `SIGFAPES_USER`/`SIGFAPES_PASSWORD`. |
| Pareceres não saem no zip/tela | Sem navegador para render PDF | A imagem Docker já traz `chromium`; local, instale Chrome ou defina `CHROME_BIN`. |
| `urlopen error [Errno 8]` | Falha de DNS/rede até o SIGFAPES | Verifique a rede; evite rodar duas sincronizações pesadas ao mesmo tempo. |
| Avaliação lenta / cara | `AVAL_AMOSTRAS=3` (triplica chamadas LLM) | Baixe para `AVAL_AMOSTRAS=1` se não precisar estabilizar a nota. |
