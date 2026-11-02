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

# Regra de negócio: projeto com conformidade >= 70% está aprovado.
LIMIAR_APROVACAO = 70


def situacao(nota) -> str:
    """APROVADO se nota >= LIMIAR_APROVACAO; REPROVADO se abaixo; — se sem nota."""
    try:
        return "APROVADO" if float(nota) >= LIMIAR_APROVACAO else "REPROVADO"
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
           aval_id: str | None = None, projeto_id: str | None = None) -> str:
    """Grava uma avaliação e devolve seu id. Reusa o id se fornecido (idempotente).
    `projeto_id` liga a avaliação à proposta do SIGFAPES."""
    aval_id = aval_id or uuid.uuid4().hex[:12]
    d = _dir(aval_id)
    os.makedirs(d, exist_ok=True)
    nota = resultado.get("grau_conformidade_geral")
    meta = {
        "id": aval_id,
        "titulo": (titulo or _titulo_do_resultado(resultado)),
        "data": _dt.datetime.now().isoformat(timespec="seconds"),
        "perfil": perfil or "",
        "nota": nota,
        "parecer": resultado.get("parecer", ""),
        "situacao": situacao(nota),
        "projeto_id": projeto_id or "",
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
                    itens.append(json.load(f))
            except (OSError, ValueError):
                continue
    itens.sort(key=lambda m: m.get("data", ""), reverse=True)
    return itens


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
        return json.load(f)


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
