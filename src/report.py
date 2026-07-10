"""Renderiza o parecer técnico EXECUTIVO em HTML a partir da análise (dict).

Renderização determinística (sem LLM): layout consistente, uma página,
dashboard com veredito, gauge de conformidade, KPIs, ressalvas em destaque.
O conteúdo textual (resumo, justificativa, recomendações) vem da análise do
Mistral; aqui é só apresentação — rápido, gratuito e previsível.
"""
import base64
import html as _html
import os

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "logo.png")


def _logo_data_uri() -> str:
    """Logo FAPES embutido como data URI (relatório self-contained p/ PDF)."""
    try:
        with open(_LOGO_PATH, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return ""


# Paleta por parecer: (cor_texto, cor_fundo, cor_borda)
PARECER_CORES = {
    "APROVAR": ("#166534", "#dcfce7", "#22c55e"),
    "APROVAR COM RESSALVAS": ("#92400e", "#fef3c7", "#f59e0b"),
    "DILIGÊNCIA": ("#9a3412", "#ffedd5", "#f97316"),
    "REPROVAR": ("#991b1b", "#fee2e2", "#ef4444"),
}
STATUS_CORES = {
    "ATENDIDO": ("#166534", "#dcfce7"),
    "PARCIAL": ("#92400e", "#fef3c7"),
    "NÃO ATENDIDO": ("#991b1b", "#fee2e2"),
    "NÃO EVIDENCIADO": ("#475569", "#e2e8f0"),
}


def _e(v) -> str:
    if v is None or v == "":
        return "—"
    return _html.escape(str(v))


def _status_norm(s: str) -> str:
    s = (s or "").strip().upper()
    for k in STATUS_CORES:
        if s.startswith(k):
            return k
    return "NÃO EVIDENCIADO"


def _chip(texto, cores) -> str:
    fg, bg = cores
    return (f'<span class="chip" style="color:{fg};background:{bg}">'
            f'{_e(texto)}</span>')


def _gauge(grau: int) -> str:
    """Donut de conformidade via conic-gradient."""
    grau = max(0, min(100, int(grau or 0)))
    cor = "#22c55e" if grau >= 80 else "#f59e0b" if grau >= 50 else "#ef4444"
    return f"""<div class="gauge" style="background:
        conic-gradient({cor} {grau*3.6:.0f}deg, #e2e8f0 0)">
        <div class="gauge-hole"><span class="gauge-num">{grau}%</span>
        <span class="gauge-lbl">conformidade</span></div></div>"""


def _tile(valor, rotulo, cor="#0f172a") -> str:
    return (f'<div class="tile"><div class="tile-num" style="color:{cor}">'
            f'{valor}</div><div class="tile-lbl">{_e(rotulo)}</div></div>')


def _atingido_chip(v) -> str:
    if v is True:
        return _chip("ATINGIDO", ("#166534", "#dcfce7"))
    if v is False:
        return _chip("NÃO ATINGIDO", ("#991b1b", "#fee2e2"))
    return _chip(str(v).upper() if v else "—", ("#92400e", "#fef3c7"))


def gerar_html(resultado: dict, client=None, titulo="Prestação de Contas Técnica") -> str:
    d = resultado or {}
    logo_uri = _logo_data_uri()
    parecer = d.get("parecer", "—")
    fg, bg, brd = PARECER_CORES.get(str(parecer).strip().upper(),
                                    ("#334155", "#f1f5f9", "#94a3b8"))
    grau = d.get("grau_conformidade_geral", 0)

    entregaveis = d.get("entregaveis", []) or []
    indicadores = d.get("indicadores", []) or []
    n_atend = sum(1 for e in entregaveis if _status_norm(e.get("status")) == "ATENDIDO")
    n_parcial = sum(1 for e in entregaveis if _status_norm(e.get("status")) == "PARCIAL")
    n_ind_ok = sum(1 for i in indicadores if i.get("atingido") is True)
    crono = d.get("cronograma", {}) or {}
    atrasadas = crono.get("etapas_atrasadas", []) or []
    no_prazo = crono.get("etapas_no_prazo", []) or []
    pendencias = d.get("pendencias_criticas", []) or []
    melhorias = d.get("pontos_de_melhoria", []) or []

    # ---- Entregáveis ----
    linhas_ent = "".join(
        f"""<tr>
          <td class="mono">{_e(e.get('id'))}</td>
          <td>{_chip(_status_norm(e.get('status')), STATUS_CORES[_status_norm(e.get('status'))])}</td>
          <td>{_e(e.get('descricao_prevista'))}</td>
          <td>{_e(e.get('descricao_realizada'))}</td>
          <td class="ev">{_e(e.get('evidencia'))}</td>
          <td>{_e(e.get('lacunas'))}</td>
          <td>{_e(e.get('recomendacao'))}</td>
        </tr>""" for e in entregaveis
    ) or '<tr><td colspan="7" class="muted">Nenhum entregável.</td></tr>'

    # ---- Indicadores ----
    linhas_ind = "".join(
        f"""<tr>
          <td>{_e(i.get('nome'))}</td>
          <td class="mono">{_e(i.get('meta_prevista'))}</td>
          <td class="mono">{_e(i.get('valor_reportado'))}</td>
          <td>{_atingido_chip(i.get('atingido'))}</td>
        </tr>""" for i in indicadores
    ) or '<tr><td colspan="4" class="muted">Nenhum indicador.</td></tr>'

    def _lista(itens, classe="") -> str:
        if not itens:
            return '<li class="muted">—</li>'
        return "".join(f'<li class="{classe}">{_e(x)}</li>' for x in itens)

    ressalvas_html = f"""
      <div class="alert">
        <div class="alert-title">⚠ Ressalvas / Pendências críticas</div>
        <ul>{_lista(pendencias, 'crit')}</ul>
      </div>""" if pendencias else ""

    # ---- Análise por arquivo (só aparece com múltiplos documentos) ----
    por_arquivo = d.get("analise_por_arquivo", []) or []
    por_arquivo_html = ""
    if len(por_arquivo) > 1:
        cards = []
        for a in por_arquivo:
            conj = str(a.get("conjunto", "")).strip().upper()
            conj_cor = ("#1d4ed8", "#dbeafe") if conj.startswith("PROJ") else ("#7c3aed", "#ede9fe")
            itens = a.get("itens_relacionados", []) or []
            itens_html = " ".join(_chip(x, ("#334155", "#e2e8f0")) for x in itens) or '<span class="muted">—</span>'
            cards.append(f"""
              <div class="doc">
                <div class="doc-head">
                  <span class="doc-nome">📄 {_e(a.get('arquivo'))}</span>
                  {_chip(conj or '—', conj_cor)}
                </div>
                <div class="doc-nat">{_e(a.get('natureza'))}</div>
                <p class="doc-res">{_e(a.get('resumo'))}</p>
                <div class="doc-row"><span class="doc-lbl">Itens relacionados:</span> {itens_html}</div>
                <div class="doc-row"><span class="doc-lbl">Trechos:</span> {_e(a.get('trechos_relevantes'))}</div>
                <div class="doc-row"><span class="doc-lbl">Observações:</span> {_e(a.get('observacoes'))}</div>
              </div>""")
        por_arquivo_html = (
            f'<h2>Análise por documento ({len(por_arquivo)} arquivos)</h2>'
            f'<div class="docs">{"".join(cards)}</div>'
        )

    # ---- Detalhamento por arquivo de prestação (mini-relatório) ----
    detalhes = d.get("detalhamento_prestacao", []) or []
    detalhe_html = ""
    if detalhes:
        blocos = []
        for det in detalhes:
            ents = det.get("entregaveis_evidenciados", []) or []
            linhas = "".join(
                f"""<tr>
                  <td class="mono">{_e(x.get('id'))}</td>
                  <td>{_chip(_status_norm(x.get('status_no_documento')), STATUS_CORES[_status_norm(x.get('status_no_documento'))])}</td>
                  <td>{_e(x.get('valor_ou_dado'))}</td>
                  <td class="ev">{_e(x.get('evidencia'))}</td>
                </tr>""" for x in ents
            ) or '<tr><td colspan="4" class="muted">Nenhum entregável evidenciado.</td></tr>'

            inds = det.get("indicadores_reportados", []) or []
            ind_linhas = "".join(
                f"""<tr><td>{_e(i.get('nome'))}</td>
                    <td class="mono">{_e(i.get('valor_reportado'))}</td>
                    <td class="ev">{_e(i.get('local'))}</td></tr>""" for i in inds
            ) or '<tr><td colspan="3" class="muted">Nenhum indicador reportado.</td></tr>'

            blocos.append(f"""
              <div class="det">
                <div class="det-head">
                  <span class="det-nome">📑 {_e(det.get('arquivo'))}</span>
                  {_chip('Período: ' + str(det.get('periodo') or '—'), ('#334155', '#e2e8f0'))}
                </div>
                <p class="det-res">{_e(det.get('resumo_detalhado'))}</p>
                <div class="det-sub">Entregáveis evidenciados neste documento</div>
                <table><thead><tr><th>ID</th><th>Status no doc.</th><th>Valor/Dado</th><th>Evidência</th></tr></thead>
                  <tbody>{linhas}</tbody></table>
                <div class="det-sub">Indicadores reportados</div>
                <table><thead><tr><th>Indicador</th><th>Valor reportado</th><th>Local</th></tr></thead>
                  <tbody>{ind_linhas}</tbody></table>
                <div class="cols" style="margin-top:12px">
                  <div class="col"><h3>Atividades relatadas</h3><ul>{_lista(det.get('atividades_relatadas'))}</ul></div>
                  <div class="col"><h3>Pendências / faltas</h3><ul>{_lista(det.get('pendencias_ou_faltas'), 'crit')}</ul></div>
                </div>
                <p class="sub"><strong>Observações:</strong> {_e(det.get('observacoes'))}</p>
              </div>""")
        detalhe_html = (
            f'<h2>Detalhamento das prestações de contas ({len(detalhes)})</h2>'
            + "".join(blocos)
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parecer Técnico Executivo — {_e(titulo)}</title>
<style>
  :root {{ --ink:#1f2937; --muted:#5b6b86; --line:#d9e0ee; --bg:#eef2f8;
    --navy:#1b2a63; --magenta:#d6296a; --lime:#a8c81e; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    font-size:13px; line-height:1.5; }}
  .page {{ max-width:920px; margin:0 auto; padding:0 28px 28px; background:#fff; }}
  .fapes-hd {{ display:flex; align-items:center; justify-content:space-between;
    gap:16px; padding:16px 0 12px; border-bottom:3px solid var(--lime); margin-bottom:6px; }}
  .fapes-hd .logo {{ height:42px; width:auto; display:block; }}
  .gov-id {{ text-align:right; color:var(--navy); font-size:11px; line-height:1.3; }}
  .gov-id strong {{ display:block; font-size:12px; }}
  .kicker {{ letter-spacing:.14em; font-size:11px; color:var(--magenta);
    text-transform:uppercase; font-weight:700; margin-top:14px; }}
  h1 {{ font-size:22px; margin:2px 0 2px; color:var(--navy); }}
  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:.06em;
    color:var(--navy); border-bottom:2px solid var(--line);
    border-left:4px solid var(--magenta); padding:0 0 6px 8px; margin:26px 0 12px; }}
  .sub {{ color:var(--muted); font-size:12px; }}
  /* HERO */
  .hero {{ display:flex; gap:22px; align-items:center; margin-top:18px;
    padding:18px; border:1px solid var(--line); border-radius:14px;
    background:linear-gradient(180deg,#fff,#fbfdff); }}
  .verdict {{ flex:1; }}
  .verdict .badge {{ display:inline-block; padding:7px 16px; border-radius:999px;
    font-weight:800; font-size:15px; color:{fg}; background:{bg};
    border:1px solid {brd}; }}
  .verdict .just {{ margin-top:10px; color:#334155; }}
  .gauge {{ width:118px; height:118px; border-radius:50%; display:flex;
    align-items:center; justify-content:center; flex:0 0 auto; }}
  .gauge-hole {{ width:86px; height:86px; background:#fff; border-radius:50%;
    display:flex; flex-direction:column; align-items:center; justify-content:center; }}
  .gauge-num {{ font-size:24px; font-weight:800; }}
  .gauge-lbl {{ font-size:9px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); }}
  /* KPIs */
  .tiles {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px;
    margin-top:14px; }}
  .tile {{ border:1px solid var(--line); border-radius:12px; padding:14px;
    text-align:center; background:#fff; }}
  .tile-num {{ font-size:26px; font-weight:800; }}
  .tile-lbl {{ font-size:11px; color:var(--muted); margin-top:2px; }}
  .summary {{ margin-top:18px; padding:16px; background:#eef2f8;
    border-left:4px solid var(--navy); border-radius:8px; font-size:14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th,td {{ text-align:left; padding:8px 9px; border-bottom:1px solid var(--line);
    vertical-align:top; }}
  th {{ color:var(--muted); font-size:10px; text-transform:uppercase;
    letter-spacing:.05em; background:#f8fafc; }}
  .chip {{ display:inline-block; padding:2px 9px; border-radius:999px;
    font-size:11px; font-weight:700; white-space:nowrap; }}
  .mono {{ font-variant-numeric:tabular-nums; }}
  .ev {{ color:#475569; font-size:11px; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  .col h3 {{ font-size:12px; margin:0 0 6px; }}
  ul {{ margin:6px 0; padding-left:18px; }} li {{ margin:3px 0; }}
  .alert {{ margin-top:18px; border:1px solid #fca5a5; background:#fef2f2;
    border-radius:12px; padding:14px 16px; }}
  .alert-title {{ font-weight:800; color:#991b1b; margin-bottom:4px; }}
  .crit {{ color:#7f1d1d; }}
  .muted {{ color:var(--muted); }}
  .docs {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .doc {{ border:1px solid var(--line); border-radius:12px; padding:14px;
    background:#fff; break-inside:avoid; }}
  .doc-head {{ display:flex; justify-content:space-between; align-items:center;
    gap:8px; margin-bottom:2px; }}
  .doc-nome {{ font-weight:700; font-size:12px; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }}
  .doc-nat {{ color:var(--muted); font-size:11px; margin-bottom:6px; }}
  .doc-res {{ margin:6px 0; }}
  .doc-row {{ font-size:11px; margin-top:5px; }}
  .doc-lbl {{ color:var(--muted); font-weight:600; text-transform:uppercase;
    letter-spacing:.04em; font-size:10px; }}
  .det {{ border:1px solid var(--line); border-radius:12px; padding:16px;
    margin-top:14px; background:#fff; break-inside:avoid; }}
  .det-head {{ display:flex; justify-content:space-between; align-items:center;
    gap:10px; margin-bottom:6px; }}
  .det-nome {{ font-weight:800; font-size:14px; }}
  .det-res {{ margin:4px 0 12px; }}
  .det-sub {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); font-weight:700; margin:14px 0 4px; }}
  .foot {{ margin-top:22px; padding:16px; border:1px solid var(--line);
    border-radius:12px; background:#fff; }}
  .foot .badge {{ display:inline-block; padding:5px 14px; border-radius:999px;
    font-weight:800; color:{fg}; background:{bg}; border:1px solid {brd}; }}
  @media print {{
    body {{ background:#fff; font-size:11px; }}
    .page {{ max-width:none; padding:0; }}
    .hero,.tile,.alert,.foot {{ break-inside:avoid; }}
    h2 {{ break-after:avoid; }}
  }}
  @media (max-width:640px) {{ .tiles{{grid-template-columns:repeat(2,1fr)}}
    .cols,.docs{{grid-template-columns:1fr}} .hero{{flex-direction:column}} }}
</style></head>
<body><div class="page">
  <div class="fapes-hd">
    <img class="logo" src="{logo_uri}" alt="FAPES">
    <span class="gov-id"><strong>GOVERNO DO ESTADO DO ESPÍRITO SANTO</strong>
      Secretaria da Ciência, Tecnologia, Inovação e Educação Profissional</span>
  </div>
  <div class="kicker">Parecer Técnico</div>
  <h1>Parecer Técnico Executivo</h1>
  <div class="sub">{_e(titulo)} — comparativo previsto × realizado</div>

  <div class="hero">
    <div class="verdict">
      <div class="kicker">Recomendação</div>
      <div class="badge">{_e(parecer)}</div>
      <div class="just">{_e(d.get('justificativa_parecer'))}</div>
    </div>
    {_gauge(grau)}
  </div>

  <div class="tiles">
    {_tile(f"{n_atend}/{len(entregaveis)}", "Entregáveis atendidos", "#166534")}
    {_tile(n_parcial, "Entregáveis parciais", "#92400e")}
    {_tile(f"{n_ind_ok}/{len(indicadores)}", "Indicadores atingidos", "#1d4ed8")}
    {_tile(len(pendencias), "Pendências críticas", "#991b1b" if pendencias else "#166534")}
  </div>

  <div class="summary">{_e(d.get('resumo_executivo'))}</div>

  {ressalvas_html}

  <h2>Entregáveis</h2>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>ID</th><th>Status</th><th>Previsto</th><th>Realizado</th>
      <th>Evidência</th><th>Lacunas</th><th>Recomendação</th></tr></thead>
    <tbody>{linhas_ent}</tbody>
  </table></div>

  <h2>Indicadores</h2>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Indicador</th><th>Meta</th><th>Reportado</th><th>Situação</th></tr></thead>
    <tbody>{linhas_ind}</tbody>
  </table></div>

  <h2>Cronograma</h2>
  <div class="cols">
    <div class="col"><h3>✓ Etapas no prazo ({len(no_prazo)})</h3>
      <ul>{_lista(no_prazo)}</ul></div>
    <div class="col"><h3>⚠ Etapas atrasadas ({len(atrasadas)})</h3>
      <ul>{_lista(atrasadas, 'crit')}</ul></div>
  </div>
  <p class="sub">{_e(crono.get('observacoes'))}</p>

  <h2>Pontos de melhoria</h2>
  <ul>{_lista(melhorias)}</ul>

  {por_arquivo_html}

  {detalhe_html}

  <div class="foot">
    <div class="kicker">Parecer final</div>
    <span class="badge">{_e(parecer)}</span> ·
    <strong>Conformidade geral:</strong> {_e(grau)}%
    <p style="margin:8px 0 0">{_e(d.get('justificativa_parecer'))}</p>
  </div>
</div></body></html>"""
