"""Persistência simples das avaliações em disco (sem banco).

Cada avaliação é uma pasta em `avaliacoes/<id>/` com:
    parecer.json   -> o resultado da análise (dict)
    meta.json      -> {id, titulo, data, perfil, nota, parecer, situacao}
    parecer.pdf    -> gerado sob demanda e cacheado

A "nota" é o grau de conformidade geral (0-100); o veredito é o campo `parecer`
(APROVAR / APROVAR COM RESSALVAS / DILIGÊNCIA / REPROVAR). A "situação" é
derivada da nota pela regra de negócio (>= LIMIAR_APROVACAO = APROVADO).
"""
import datetime as _dt
import json
import os
import re
import uuid

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "avaliacoes")

# Regra de negócio: projeto com conformidade >= limiar (%) está aprovado.
# Editável pelo usuário (persistido em config.json); padrão 70.
LIMIAR_PADRAO = 70
_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


def get_limiar() -> int:
    """Limiar de aprovação atual (%) — lido do config, padrão LIMIAR_PADRAO."""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return int(json.load(f).get("limiar", LIMIAR_PADRAO))
    except (OSError, ValueError, TypeError):
        return LIMIAR_PADRAO


def set_limiar(valor) -> int:
    """Define o limiar de aprovação (0–100). Devolve o valor aplicado."""
    n = max(0, min(100, int(float(valor))))
    cfg = {}
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    cfg["limiar"] = n
    with open(_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return n


# Compat: alguns pontos referenciam a constante; reflete o valor atual.
LIMIAR_APROVACAO = get_limiar()


def situacao(nota) -> str:
    """APROVADO se nota >= limiar atual; REPROVADO se abaixo; — se sem nota."""
    try:
        return "APROVADO" if float(nota) >= get_limiar() else "REPROVADO"
    except (TypeError, ValueError):
        return "—"


def _dir(aval_id: str) -> str:
    return os.path.join(BASE, aval_id)


def _titulo_do_resultado(resultado: dict) -> str:
    """Deriva um título: campo explícito, nome do projeto no resumo, ou genérico."""
    for campo in ("titulo", "projeto", "nome_projeto"):
        v = resultado.get(campo)
        if isinstance(v, str) and v.strip():
            return v.strip()
    resumo = str(resultado.get("resumo_executivo", ""))
    m = re.search(r"projeto\s+([A-ZÀ-Ý][\wÀ-ÿ\-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ\-]+){0,3})", resumo)
    if m:
        return m.group(1).strip()
    return "Projeto sem título"


def salvar(resultado: dict, titulo: str | None = None, perfil: str | None = None,
           aval_id: str | None = None, projeto_id: str | None = None,
           relatorio_file: str | None = None, relatorio_nome: str | None = None) -> str:
    """Grava uma avaliação e devolve seu id. Reusa o id se fornecido (idempotente).
    `projeto_id` liga a avaliação à proposta do SIGFAPES; `relatorio_file`/
    `relatorio_nome` identificam O DOCUMENTO avaliado (um projeto tem vários
    relatórios parciais + um final, cada um com sua nota)."""
    aval_id = aval_id or uuid.uuid4().hex[:12]
    d = _dir(aval_id)
    os.makedirs(d, exist_ok=True)
    nota = resultado.get("grau_conformidade_geral")
    agora = _dt.datetime.now()
    meta = {
        "id": aval_id,
        "titulo": (titulo or _titulo_do_resultado(resultado)),
        "data": agora.isoformat(timespec="seconds"),
        "ts": agora.timestamp(),  # alta resolução p/ ordenar sem empate
        "perfil": perfil or "",
        "nota": nota,
        "parecer": resultado.get("parecer", ""),
        "situacao": situacao(nota),
        "projeto_id": projeto_id or "",
        "relatorio_file": str(relatorio_file or ""),
        "relatorio_nome": relatorio_nome or "",
        "tipo_relatorio": resultado.get("tipo_relatorio", ""),
        "periodo_relatorio": resultado.get("periodo_relatorio", ""),
    }
    with open(os.path.join(d, "parecer.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # PDF cacheado fica obsoleto quando o parecer muda: remove para regerar.
    pdf = os.path.join(d, "parecer.pdf")
    if os.path.exists(pdf):
        os.remove(pdf)
    return aval_id


def listar() -> list[dict]:
    """Metadados de todas as avaliações, mais recentes primeiro."""
    if not os.path.isdir(BASE):
        return []
    itens = []
    for nome in os.listdir(BASE):
        meta_path = os.path.join(BASE, nome, "meta.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    m = json.load(f)
                m["situacao"] = situacao(m.get("nota"))  # recomputa com o limiar atual
                itens.append(m)
            except (OSError, ValueError):
                continue
    # ts (alta resolução) quebra empates de same-second; fallback p/ data.
    itens.sort(key=lambda m: (m.get("ts", 0.0), m.get("data", "")), reverse=True)
    return itens


def historico(projeto_id: str) -> list[dict]:
    """Todas as avaliações de um projeto, mais recentes primeiro (histórico)."""
    pid = str(projeto_id)
    return [m for m in listar() if str(m.get("projeto_id") or "") == pid]


def _chave_doc(m: dict) -> str:
    """Identidade do DOCUMENTO avaliado (relatório), para deduplicar por doc.
    Novo: file id exato do relatório. Legado (sem file): agrupa por tipo+período
    para colapsar rodadas repetidas do mesmo documento."""
    f = m.get("relatorio_file")
    if f:
        return f"file:{f}"
    return "tp:" + (m.get("tipo_relatorio") or "?") + "|" + (m.get("periodo_relatorio") or "?")


def _latest_por_doc(hist: list[dict]) -> list[dict]:
    """Dada uma lista de avaliações (mais recentes primeiro), mantém a mais
    recente de CADA documento. Um projeto tem vários relatórios (parciais +
    final); cada documento tem sua própria nota atual."""
    vistos, out = set(), []
    for m in hist:
        chave = _chave_doc(m)
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(m)
    return out


def por_documento(projeto_id: str) -> list[dict]:
    """Avaliação atual de CADA documento (relatório) do projeto, em ordem
    cronológica (parciais → final). Uma nota por documento."""
    docs = _latest_por_doc(historico(projeto_id))
    return sorted(docs, key=lambda m: (m.get("ts", 0.0), m.get("data", "")))


def _mediana(nums: list) -> float | None:
    vals = sorted(float(n) for n in nums if isinstance(n, (int, float)))
    if not vals:
        return None
    meio = len(vals) // 2
    if len(vals) % 2:
        return vals[meio]
    return (vals[meio - 1] + vals[meio]) / 2


def avaliacao_atual(projeto_id: str) -> dict | None:
    """A avaliação mais recente de um projeto (ou None). Para referência pontual."""
    h = historico(projeto_id)
    return h[0] if h else None


def _resumo_de_docs(projeto_id: str, docs: list[dict]) -> dict | None:
    """Monta o resumo do projeto a partir das avaliações (uma por documento):
    nota geral = MEDIANA das notas; `id`/`parecer` apontam para um parecer
    representativo (o final, senão o mais recente) para abrir/baixar."""
    if not docs:
        return None
    med = _mediana([d.get("nota") for d in docs])
    finais = [d for d in docs if (d.get("tipo_relatorio") or "").upper().startswith("FINAL")]
    rep = max(finais or docs, key=lambda m: (m.get("ts", 0.0), m.get("data", "")))
    return {
        "projeto_id": str(projeto_id),
        "nota": round(med) if med is not None else None,
        "situacao": situacao(med) if med is not None else "—",
        "n_docs": len(docs),
        "id": rep.get("id"),
        "parecer": rep.get("parecer", ""),
        "tipo_relatorio": rep.get("tipo_relatorio", ""),
        "periodo_relatorio": rep.get("periodo_relatorio", ""),
    }


def resumo_projeto(projeto_id: str) -> dict | None:
    """Nota GERAL da proposta = MEDIANA das notas dos documentos (parciais +
    final). None se não há avaliação."""
    return _resumo_de_docs(projeto_id, por_documento(projeto_id))


def por_projeto() -> dict:
    """Mapa projeto_id -> RESUMO do projeto (nota geral = mediana dos documentos)."""
    por_pid: dict[str, list] = {}
    for m in listar():  # ordenado por data desc
        pid = str(m.get("projeto_id") or "")
        if pid:
            por_pid.setdefault(pid, []).append(m)
    mapa = {}
    for pid, hist in por_pid.items():
        docs = sorted(_latest_por_doc(hist), key=lambda m: (m.get("ts", 0.0), m.get("data", "")))
        resumo = _resumo_de_docs(pid, docs)
        if resumo:
            mapa[pid] = resumo
    return mapa


def carregar(aval_id: str) -> dict | None:
    """Resultado completo de uma avaliação, ou None se não existir."""
    path = os.path.join(_dir(aval_id), "parecer.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _meta(aval_id: str) -> dict | None:
    path = os.path.join(_dir(aval_id), "meta.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    m["situacao"] = situacao(m.get("nota"))  # recomputa com o limiar atual
    return m


def pdf_path(aval_id: str) -> str | None:
    """Caminho do PDF cacheado (gera na primeira chamada). None se não existir a avaliação."""
    resultado = carregar(aval_id)
    if resultado is None:
        return None
    out = os.path.join(_dir(aval_id), "parecer.pdf")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    from pdf import html_para_pdf
    from report import gerar_html
    meta = _meta(aval_id) or {}
    titulo = meta.get("titulo") or "Prestação de Contas Técnica"
    html = gerar_html(resultado, titulo=titulo)
    return html_para_pdf(html, out)
