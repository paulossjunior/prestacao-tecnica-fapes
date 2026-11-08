# Tutorial — do zero ao primeiro parecer

Este tutorial te leva, passo a passo, de uma máquina sem nada até **ver um parecer
técnico gerado** pela aplicação. Siga na ordem; cada passo diz o que você deve ver
antes de ir ao próximo.

> Caminho único e mais simples: rodar a **imagem pronta** com Docker. Para outras
> formas (compose, Dokploy, Render, dev local), veja [INSTALACAO.md](INSTALACAO.md).

**Tempo estimado:** ~15 minutos (fora o download da imagem).

---

## O que você vai precisar ter em mãos

- Um computador com **Docker** instalado (Windows, macOS ou Linux).
- **Login e senha do SIGFAPES** (um usuário com acesso às propostas).
- Uma **chave da API da OpenAI** (começa com `sk-...`).

---

## Passo 1 — Instalar o Docker

Se ainda não tem:

- **Windows/macOS:** instale o **Docker Desktop** (https://www.docker.com/products/docker-desktop) e abra o app.
- **Linux:** instale o **Docker Engine** pela documentação oficial da sua distro.

Confirme que está funcionando:

```bash
docker --version
```

✅ Você deve ver algo como `Docker version 2x.x.x`. Se der erro, o Docker não está
instalado/rodando — resolva isso antes de continuar.

---

## Passo 2 — Subir a aplicação

Copie o comando abaixo, **troque os 3 valores em MAIÚSCULAS** pelos seus e rode no
terminal:

```bash
docker run -d --name prestacao -p 8080:8000 \
  -e LLM_PROVIDER=openai \
  -e OPENAI_API_KEY=SUA_CHAVE_OPENAI \
  -e OPENAI_MODEL=gpt-4o \
  -e OPENAI_OCR_MODEL=gpt-5.4-nano \
  -e SIGFAPES_USER=SEU_LOGIN_SIGFAPES \
  -e SIGFAPES_PASSWORD=SUA_SENHA_SIGFAPES \
  -v prestacao_avaliacoes:/app/avaliacoes \
  -v prestacao_cache:/app/cache \
  ghcr.io/paulossjunior/prestacao-tecnica-fapes:latest
```

> Os dois `-v ...` criam volumes que **guardam suas avaliações** mesmo se o
> container for recriado. Não use `SIGFAPES_USER=USER` com o nome `USER`: use
> exatamente `SIGFAPES_USER`.

Confira que o container está de pé:

```bash
docker ps
```

✅ Você deve ver a linha do container `prestacao` com status `Up` e a porta
`0.0.0.0:8080->8000/tcp`.

Se aparecer **privado** ao baixar a imagem, faça login no registry antes
(token do GitHub com escopo `read:packages`):

```bash
echo SEU_TOKEN | docker login ghcr.io -u SEU_USUARIO_GITHUB --password-stdin
```

---

## Passo 3 — Abrir no navegador

Acesse:

```
http://localhost:8080/propostas
```

✅ A página abre com o título e a área de propostas. Na **primeira vez ela está
vazia** — é esperado; vamos preencher no próximo passo.

---

## Passo 4 — Sincronizar as propostas (faz login no SIGFAPES)

Clique no botão **Sincronizar**. A aplicação entra no SIGFAPES com o seu usuário e
baixa a lista de propostas.

✅ Após alguns instantes, a lista é preenchida com as propostas, agrupadas por
edital, e um mini-painel mostra totais (Propostas / Avaliados / Aprovados / Não
passaram). Se a lista continuar vazia, confira `SIGFAPES_USER`/`SIGFAPES_PASSWORD`
(veja o Passo 7, Problemas).

---

## Passo 5 — Avaliar um projeto

1. Clique em **Abrir** numa proposta (ou no título) para ver o detalhe.
2. Na tela de detalhe, dispare a avaliação do projeto.

A aplicação baixa o **relatório técnico (Anexo VI)** e as **evidências**
(artigos, trabalhos), faz OCR quando necessário e pede ao modelo a análise. Cada
documento é avaliado algumas vezes e a nota é a **mediana** (estabilização).

✅ Ao terminar, aparece a **nota geral**, a **situação** (APROVADO/REPROVADO,
conforme o limiar de 70%), o **parecer** e as **notas por documento** (parcial/
final), incluindo o **histórico** das rodadas (ex.: `60 · 60 · 60 → mediana 60%`).

> A avaliação chama a OpenAI e pode levar 1–3 min por documento.

---

## Passo 6 — Baixar o parecer

- No detalhe, clique em **⬇ Parecer do projeto (consolidado)** para baixar o PDF
  com o veredito geral + o resumo do parecer de cada relatório.
- Na lista, você também pode **selecionar vários projetos** e usar **⬇ Baixar PDFs
  (zip)** — o zip traz, por projeto: o projeto, os relatórios, o parecer de cada
  relatório e o parecer consolidado.

✅ O PDF abre/baixa corretamente. Pronto — você instalou, sincronizou, avaliou e
baixou um parecer.

---

## Passo 7 — Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `docker: command not found` | Docker não instalado/rodando (Passo 1). |
| Lista vazia após Sincronizar | Verifique `SIGFAPES_USER`/`SIGFAPES_PASSWORD`; veja os logs: `docker logs prestacao`. |
| "Defina USER e PASSWORD" | Você usou `USER` em vez de `SIGFAPES_USER`. |
| Avaliação muito lenta/cara | Reduza as rodadas: adicione `-e AVAL_AMOSTRAS=1` no `docker run`. |
| Erro de rede ao sincronizar/avaliar | Tente de novo; evite duas sincronizações pesadas ao mesmo tempo. |

Comandos úteis:

```bash
docker logs -f prestacao     # acompanhar os logs
docker stop prestacao        # parar
docker start prestacao       # iniciar de novo (dados preservados nos volumes)
```

---

## Próximos passos

- Fixar uma versão específica da imagem: troque `:latest` por `:X.Y.Z`
  (ex.: `:1.0.0`). As versões são publicadas automaticamente a cada release.
- Colocar em um servidor (Dokploy, Render) ou rodar em desenvolvimento:
  veja [INSTALACAO.md](INSTALACAO.md).
