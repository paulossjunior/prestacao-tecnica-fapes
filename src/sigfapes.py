"""Cliente do SIGFAPES: login + download das propostas (CSV), com tratamento
de timeout para o servidor lento (PHP 5.6).

Chave do timeout: lê a resposta em streaming com timeout POR LEITURA
(inatividade do socket), não um teto total. O `csv.php` gera a planilha inteira
antes de enviar e o envio é lento; enquanto chegam bytes dentro da janela de
inatividade, o download continua — o que derruba um `curl -m <total>` aqui
completa por streaming.

Uso (CLI):
    python src/sigfapes.py              # baixa/atualiza o cache de propostas
    python src/sigfapes.py --status "Projeto Concluído em fase de prestação de contas"

Uso (programático):
    import sigfapes
    props = sigfapes.listar_propostas(status="...")   # usa cache, baixa se faltar
    grupos = sigfapes.agrupar_por_edital(props)
"""
import csv
import http.cookiejar
import io
import os
import re
import socket
import time
import urllib.parse
import urllib.request

from dotenv import dotenv_values, load_dotenv

load_dotenv()
# `USER` colide com a env var padrão do Unix (nome do usuário do SO), então
# `os.getenv("USER")` traria o usuário do SO em vez do login do SIGFAPES. Lemos
# as credenciais direto do arquivo .env (prioridade) para evitar essa colisão.
_ENVFILE = dotenv_values()


def _cfg(chave: str) -> str:
    return (_ENVFILE.get(chave) or os.getenv(chave) or "")


SITE = (_cfg("SITE") or "http://201.62.44.41/").rstrip("/")
USUARIO = _cfg("USER")
SENHA = _cfg("PASSWORD")

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
CSV_CACHE = os.path.join(_CACHE_DIR, "propostas.csv")

# Colunas da planilha de propostas que interessam para a lista.
_COLS = {
    "edital": "EDITAL",
    "processo": "Nº DO PROCESSO",
    "titulo": "TITULO DO PROJETO",
    "situacao": "SITUACAO",
    "protocolo": "PROTOCOLO",
    "pesquisador": "PESQUISADOR",
    "instituicao": "INSTITUIÇÃO EXECUTORA",
    "data": "DATA SUBMISSAO",
}


def _novo_opener() -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def login(opener: urllib.request.OpenerDirector | None = None,
          timeout: int = 30) -> urllib.request.OpenerDirector:
    """Autentica e devolve um opener com o cookie de sessão."""
    if not USUARIO or not SENHA:
        raise RuntimeError("Defina USER e PASSWORD no .env para o login do SIGFAPES.")
    opener = opener or _novo_opener()
    dados = urllib.parse.urlencode({"login": USUARIO, "senha": SENHA}).encode()
    req = urllib.request.Request(f"{SITE}/projetos/controle.php", data=dados)
    with opener.open(req, timeout=timeout) as resp:
        resp.read(1024)  # consome o redirect/corpo; o cookie fica no jar
    return opener


def _preparar_busca(opener, timeout: int = 90) -> None:
    """Prime a sessão: o csv.php exporta conforme a última busca feita.
    Uma busca 'Todos' (5[]=0) coloca todas as propostas no escopo do export."""
    dados = urllib.parse.urlencode({"5[]": "0", "submit": "Buscar"}).encode()
    req = urllib.request.Request(f"{SITE}/admin/admin.php?id=5", data=dados)
    with opener.open(req, timeout=timeout) as resp:
        resp.read()  # descarta o HTML da busca; o que importa é o estado na sessão


def _baixar_stream(opener, url: str, destino: str, read_timeout: int = 180,
                   chunk: int = 65536, min_bytes: int = 1) -> int:
    """Baixa `url` para `destino` lendo em blocos (timeout por leitura, tolera
    servidor lento). Só substitui o arquivo final se o download tiver pelo menos
    `min_bytes` — assim uma resposta curta/erro NÃO destrói um cache bom."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = f"{destino}.part.{os.getpid()}"  # único por processo: evita corrida no .part
    total = 0
    req = urllib.request.Request(url)
    with opener.open(req, timeout=read_timeout) as resp, open(tmp, "wb") as f:
        sock = resp.fp.raw._sock if hasattr(resp, "fp") else None
        if sock is not None:
            sock.settimeout(read_timeout)
        while True:
            bloco = resp.read(chunk)
            if not bloco:
                break
            f.write(bloco)
            total += len(bloco)
    if total < min_bytes:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return total  # mantém o arquivo final anterior intacto
    os.replace(tmp, destino)
    return total


def baixar_propostas_csv(force: bool = False, tentativas: int = 4,
                         read_timeout: int = 180) -> str:
    """Baixa TODAS as propostas (CSV) para o cache, tratando timeout com
    streaming + retentativas (backoff). Reusa o cache se já existir e !force.
    Em falha total, mantém um cache anterior se houver."""
    if os.path.exists(CSV_CACHE) and not force:
        return CSV_CACHE
    url = f"{SITE}/admin/csv/csv.php"
    opener = login()
    _preparar_busca(opener)
    erro = None
    for i in range(1, tentativas + 1):
        try:
            n = _baixar_stream(opener, url, CSV_CACHE, read_timeout=read_timeout,
                               min_bytes=1000)  # não sobrescreve cache bom com resposta curta
            if n < 1000:  # resposta curta demais = sessão caiu / vazio
                raise RuntimeError(f"CSV muito curto ({n} bytes); sessão expirada?")
            return CSV_CACHE
        except (socket.timeout, TimeoutError, urllib.error.URLError,
                RuntimeError, ConnectionError) as e:
            erro = e
            espera = min(30, 5 * i)
            print(f"[tentativa {i}/{tentativas}] falhou: {e}. "
                  f"Relogin e retry em {espera}s...", flush=True)
            time.sleep(espera)
            try:
                opener = login()
                _preparar_busca(opener)
            except Exception as le:  # noqa: BLE001
                erro = le
    if os.path.exists(CSV_CACHE):
        print(f"AVISO: download falhou ({erro}); usando cache existente.", flush=True)
        return CSV_CACHE
    raise RuntimeError(f"Não foi possível baixar as propostas: {erro}")


def _ler_csv(caminho: str) -> list[dict]:
    with open(caminho, "rb") as f:
        bruto = f.read()
    # Produção (sigfapes.es.gov.br) é UTF-8; o IP antigo era latin-1. Tenta UTF-8
    # e cai para latin-1 (que nunca falha) preservando os acentos corretos.
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    linhas = texto.splitlines()
    out = []
    for row in csv.DictReader(linhas, delimiter=";"):
        out.append({k: (row.get(col, "") or "").strip() for k, col in _COLS.items()})
    return out


def listar_propostas(status=None, force: bool = False) -> list[dict]:
    """Propostas do cache (baixa se faltar). `status` pode ser uma string ou uma
    lista de status; filtra pelas situações exatas dadas (vazio = todas)."""
    caminho = baixar_propostas_csv(force=force)
    props = _ler_csv(caminho)
    if status:
        alvos = [status] if isinstance(status, str) else list(status)
        alvos = {s.strip().casefold() for s in alvos if s and s.strip()}
        if alvos:
            props = [p for p in props if p["situacao"].casefold() in alvos]
    return props


# Situações do grupo "Projeto CONTRATADO" no SIGFAPES (ordem da própria UI).
STATUS_CONTRATADO = [
    "Projeto Em Andamento",
    "Projeto Concluído",
    "Projeto Cancelado",
    "Projeto Substituído",
    "Projeto NÃO Concluído",
    "Projeto Concluído em fase de prestação de contas",
    "Projeto Concluído e homologado",
    "Projeto Concluído, homologado e em processo de doação de bens",
    "Projeto Concluído e não homologado",
    "Processo Encerrado",
    "Projeto em Tomada de Contas Especial",
    "Projeto Concluído e com pendências",
    "Em recuperação de crédito - PGE",
    "TCE Concluída, processo em deliberação no Conselho",
]


def status_disponiveis() -> list[dict]:
    """Status de 'Projeto CONTRATADO' (lista canônica do SIGFAPES) com a contagem
    de propostas no cache ao lado (0 se ausente). Não dispara download."""
    import collections
    import os as _os
    cont = collections.Counter()
    if _os.path.exists(CSV_CACHE):
        cont = collections.Counter(p["situacao"] for p in _ler_csv(CSV_CACHE) if p["situacao"])
    opts = [{"status": s, "n": cont.get(s, 0)} for s in STATUS_CONTRATADO]
    # Qualquer status no cache fora da lista canônica entra no fim (não perder dado).
    extras = sorted(set(cont) - set(STATUS_CONTRATADO))
    opts += [{"status": s, "n": cont[s]} for s in extras]
    return opts


def editais_disponiveis() -> list[dict]:
    """Editais presentes no cache, com contagem (ordem alfabética). Sem download."""
    import collections
    import os as _os
    if not _os.path.exists(CSV_CACHE):
        return []
    cont = collections.Counter(p["edital"] for p in _ler_csv(CSV_CACHE) if p["edital"])
    return [{"edital": e, "n": cont[e]} for e in sorted(cont, key=str.casefold)]


def projeto_id_do_protocolo(protocolo: str) -> str:
    """O projeto_id é o 1º campo do protocolo: <projeto_id>.<edital>.<pesq>.<data>."""
    return (protocolo or "").split(".")[0].strip()


def proposta_por_projeto_id(projeto_id: str, status: str | None = None) -> dict | None:
    """Acha uma proposta pelo projeto_id (via protocolo)."""
    for p in listar_propostas(status=status):
        if projeto_id_do_protocolo(p["protocolo"]) == str(projeto_id):
            return p
    return None


_PROJ_PDF_DIR = os.path.join(_CACHE_DIR, "projetos")


def baixar_projeto_pdf(projeto_id: str, force: bool = False,
                       read_timeout: int = 180) -> str:
    """Baixa o PDF da proposta (gerado pelo SIGFAPES) para cache e devolve o caminho."""
    projeto_id = str(projeto_id)
    destino = os.path.join(_PROJ_PDF_DIR, f"{projeto_id}.pdf")
    if os.path.exists(destino) and os.path.getsize(destino) > 0 and not force:
        return destino
    url = (f"{SITE}/projetos/imprimir_pdf.php?projeto_id={projeto_id}"
           "&admin=1&original=1&visualiza=1&home=1")
    opener = login()
    n = _baixar_stream(opener, url, destino, read_timeout=read_timeout, min_bytes=500)
    if n < 500:
        raise RuntimeError(f"PDF do projeto {projeto_id} veio vazio ({n} bytes).")
    return destino


_REL_PDF_DIR = os.path.join(_CACHE_DIR, "relatorios")

# Documentos da prestação ficam na "Área de Projeto Contratado", seção
# "Gestão de Documentos" (passo=126), e baixam por contratados/downloadanexo.php.
_PASSO_DOCUMENTOS = 126
# Nome do documento que é o relatório técnico DO PROJETO (o "realizado").
# "Anexo VI" ou "Relatório Técnico (Final/Parcial/de Projeto/de Pesquisa)".
_RE_RELATORIO = re.compile(r"anexo\s*vi\b|relat[óo]rio\s*t[ée]cnic", re.I)
# Exclui relatórios individuais de bolsista (não são o relatório do projeto).
_RE_NAO_RELATORIO = re.compile(r"bolsista|monitora?\b", re.I)


def _eh_relatorio_projeto(doc: dict) -> bool:
    txt = f"{doc.get('nome','')} {doc.get('descricao','')}"
    return bool(_RE_RELATORIO.search(txt)) and not _RE_NAO_RELATORIO.search(txt)


def listar_documentos_prestacao(projeto_id: str) -> list[dict]:
    """Lista os documentos da prestação de contas de um projeto contratado.

    Fluxo (Informações → Projeto Contratado → Documentos):
    `contratados.php?projeto_id=<pid>&modo=1&passo=126&admin=1` → tabela de anexos,
    cada um baixável por `contratados/downloadanexo.php?file=<fid>`.
    Devolve [{file, nome, descricao, data, pesquisador}], mais recentes por último."""
    projeto_id = str(projeto_id)
    url = (f"{SITE}/contratados.php?projeto_id={projeto_id}"
           f"&modo=1&passo={_PASSO_DOCUMENTOS}&admin=1")
    opener = login()
    with opener.open(urllib.request.Request(url), timeout=90) as resp:
        html = resp.read().decode("utf-8", "replace")
    docs = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        m = re.search(r"downloadanexo\.php\?file=(\d+)", tr)
        if not m:
            continue
        celulas = [" ".join(re.sub(r"<[^>]+>", " ", c).split())
                   for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        celulas = [c for c in celulas if c]
        docs.append({
            "file": m.group(1),
            "nome": celulas[0] if celulas else "",
            "descricao": celulas[1] if len(celulas) > 1 else "",
            "data": next((c for c in celulas if re.search(r"\d{2}/\d{2}/\d{4}", c)), ""),
            "pesquisador": celulas[-1] if len(celulas) > 2 else "",
        })
    return docs


def baixar_anexo(file_id: str, destino: str, force: bool = False) -> str:
    """Baixa um anexo da prestação (contratados/downloadanexo.php) para `destino`."""
    if os.path.exists(destino) and os.path.getsize(destino) > 0 and not force:
        return destino
    opener = login()
    url = f"{SITE}/contratados/downloadanexo.php?file={file_id}"
    n = _baixar_stream(opener, url, destino, min_bytes=500)
    if n < 500:
        raise RuntimeError(f"Anexo {file_id} veio vazio ({n} bytes).")
    return destino


def listar_relatorios(projeto_id: str) -> list[dict]:
    """Todos os documentos de relatório técnico (Anexo VI) da prestação — pode
    haver vários (parciais por período + final). Mais antigos primeiro."""
    docs = listar_documentos_prestacao(projeto_id)
    rel = [d for d in docs if _eh_relatorio_projeto(d)]
    rel.sort(key=lambda d: d.get("data", ""))  # cronológico: parcial 1, 2, final
    return rel


def baixar_relatorio_por_file(file_id: str, destino: str, force: bool = False) -> str:
    """Baixa um relatório específico (por file id) para `destino`."""
    return baixar_anexo(file_id, destino, force=force)


def baixar_relatorio_pdf(projeto_id: str, force: bool = False) -> str:
    """Baixa o relatório técnico (Anexo VI) da prestação de contas do projeto.

    Localiza, entre os documentos da prestação (passo=126), aquele cujo nome é
    "Anexo VI - Relatório Técnico" e baixa via downloadanexo.php."""
    projeto_id = str(projeto_id)
    destino = os.path.join(_REL_PDF_DIR, f"{projeto_id}.pdf")
    if os.path.exists(destino) and os.path.getsize(destino) > 0 and not force:
        return destino
    docs = listar_documentos_prestacao(projeto_id)
    rel = next((d for d in docs if _eh_relatorio_projeto(d)), None)
    if rel is None:
        raise RuntimeError(
            f"Relatório técnico (Anexo VI) não encontrado nos documentos do "
            f"projeto {projeto_id}. Docs: {[d['nome'] for d in docs] or 'nenhum'}."
        )
    return baixar_anexo(rel["file"], destino, force=force)


def agrupar_por_edital(props: list[dict]) -> list[dict]:
    """Agrupa numa lista [{edital, propostas:[...]}], editais em ordem alfabética."""
    grupos: dict[str, list] = {}
    for p in props:
        grupos.setdefault(p["edital"] or "(sem edital)", []).append(p)
    return [{"edital": ed, "propostas": grupos[ed]}
            for ed in sorted(grupos, key=str.casefold)]


if __name__ == "__main__":
    import sys
    st = None
    if "--status" in sys.argv:
        st = sys.argv[sys.argv.index("--status") + 1]
    forcar = "--force" in sys.argv
    t0 = time.time()
    props = listar_propostas(status=st, force=forcar)
    print(f"propostas: {len(props)}"
          + (f" com status {st!r}" if st else "")
          + f"  ({time.time() - t0:.0f}s)")
    for g in agrupar_por_edital(props):
        print(f"\n### {g['edital']}  ({len(g['propostas'])})")
        for p in g["propostas"]:
            print(f"  - [{p['protocolo']}] {p['pesquisador'][:28]:28} | {p['titulo'][:55]}")
