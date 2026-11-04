"""POC web: avaliação técnica de prestação de contas (FAPES/IFES) via Mistral."""
import os
import threading
import uuid

from dotenv import load_dotenv
from flask import (Flask, Response, abort, jsonify, render_template, request,
                   send_file)

import sigfapes
import store
from analyzer import analisar
from extract import extract_folder, extract_pairs
from prompts import get_system_prompt, listar_perfis
from report import gerar_html

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB por requisição

# Processamento assíncrono: a análise leva minutos; não segura a conexão HTTP.
# Job store em memória (ok para 1 worker + threads; POC sem persistência).
_jobs = {}
_lock = threading.Lock()


def _set(job_id, **kv):
    with _lock:
        _jobs.setdefault(job_id, {}).update(kv)


def _run_job(job_id, projeto_pairs, prestacao_pairs, system_prompt=None, perfil=None):
    try:
        projeto = extract_pairs(projeto_pairs)
        prestacao = extract_pairs(prestacao_pairs)
        resultado = analisar(projeto, prestacao, system_prompt=system_prompt, perfil=perfil)
        aval_id = store.salvar(resultado, perfil=perfil)
        _set(job_id, status="done", resultado=resultado, aval_id=aval_id)
    except Exception as e:  # noqa: BLE001 — devolve a mensagem ao cliente
        _set(job_id, status="error", erro=str(e))


@app.route("/avaliar")
def avaliar_individual():
    """Avaliação individual: envia projeto + prestação manualmente e gera o parecer."""
    return render_template("index.html")


@app.route("/perfis")
def perfis_endpoint():
    """Tipos de projeto disponíveis em .agents/perfis/."""
    return jsonify({"perfis": listar_perfis()})


@app.route("/prompt")
def prompt_endpoint():
    """Prompt de sistema (schema + perfil + regras + skill de escrita)."""
    perfil = request.args.get("perfil")
    return jsonify({"perfil": perfil or "", "system_prompt": get_system_prompt(perfil)})


@app.route("/analisar", methods=["POST"])
def analisar_endpoint():
    projeto_files = request.files.getlist("projeto")
    prestacao_files = request.files.getlist("prestacao")

    projeto_pairs = [(f.filename, f.read()) for f in projeto_files if f and f.filename]
    prestacao_pairs = [(f.filename, f.read()) for f in prestacao_files if f and f.filename]

    if not projeto_pairs or not prestacao_pairs:
        return jsonify({"erro": "Envie ao menos um arquivo de projeto e um de prestação."}), 400

    # Prompt editado na aba "Prompt"; vazio = monta o padrão do perfil escolhido.
    system_prompt = (request.form.get("system_prompt") or "").strip() or None
    perfil = (request.form.get("perfil") or "").strip() or None

    job_id = uuid.uuid4().hex
    _set(job_id, status="processing")
    threading.Thread(
        target=_run_job,
        args=(job_id, projeto_pairs, prestacao_pairs, system_prompt, perfil),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id, "status": "processing"}), 202


@app.route("/status/<job_id>")
def status_endpoint(job_id):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    return jsonify(job)


@app.route("/relatorio", methods=["POST"])
def relatorio_endpoint():
    """Recebe a análise (JSON) e devolve o parecer técnico em HTML."""
    resultado = request.get_json(silent=True)
    if not isinstance(resultado, dict):
        return jsonify({"erro": "Envie a análise (JSON) no corpo da requisição."}), 400
    try:
        html = gerar_html(resultado)
    except (RuntimeError, ValueError) as e:
        return jsonify({"erro": str(e)}), 502
    return Response(html, mimetype="text/html")


STATUS_PRESTACAO = "Projeto Concluído em fase de prestação de contas"

# Sincronização das propostas (download pesado): roda em background, 1 por vez.
_sync = {"status": "idle", "msg": "", "ts": None}
_sync_lock = threading.Lock()


def _run_sync():
    try:
        import datetime
        caminho = sigfapes.baixar_propostas_csv(force=True)
        n = len(sigfapes.listar_propostas(status=STATUS_PRESTACAO))
        with _sync_lock:
            _sync.update(status="done", ts=datetime.datetime.now().isoformat(timespec="seconds"),
                         msg=f"{n} proposta(s) em prestação de contas.")
    except Exception as e:  # noqa: BLE001
        with _sync_lock:
            _sync.update(status="error", msg=str(e))


@app.route("/propostas/sincronizar", methods=["POST"])
def propostas_sincronizar():
    """Dispara o download das propostas em background (não bloqueia a requisição)."""
    with _sync_lock:
        if _sync["status"] == "running":
            return jsonify(_sync), 202
        _sync.update(status="running", msg="Baixando do SIGFAPES...")
    threading.Thread(target=_run_sync, daemon=True).start()
    return jsonify(_sync), 202


# Avaliação em lote das propostas selecionadas (download + LLM): 1 execução por vez.
_batch = {"status": "idle", "total": 0, "done": 0, "ok": 0, "itens": [], "msg": ""}
_batch_lock = threading.Lock()


def _avaliar_um(projeto_id, prop):
    """Avalia uma proposta: baixa projeto + relatório, roda LLM, salva. Devolve (ok, msg)."""
    import tempfile
    sigfapes.baixar_projeto_pdf(projeto_id)                 # projeto (ok)
    rel = sigfapes.baixar_relatorio_pdf(projeto_id)         # relatório (bloqueio atual)
    with tempfile.TemporaryDirectory() as d:
        import os as _os
        import shutil
        _os.makedirs(_os.path.join(d, "projeto")); _os.makedirs(_os.path.join(d, "prestacao"))
        shutil.copy(sigfapes.baixar_projeto_pdf(projeto_id), _os.path.join(d, "projeto"))
        shutil.copy(rel, _os.path.join(d, "prestacao"))
        proj = extract_folder(_os.path.join(d, "projeto"))
        prest = extract_folder(_os.path.join(d, "prestacao"))
    resultado = analisar(proj, prest, perfil="inovacao")
    store.salvar(resultado, titulo=(prop.get("titulo") or f"Projeto {projeto_id}")[:80],
                 perfil="inovacao", projeto_id=projeto_id)
    return True, f"nota {resultado.get('grau_conformidade_geral')}"


def _run_batch(ids):
    por_id = {sigfapes.projeto_id_do_protocolo(p["protocolo"]): p
              for p in sigfapes.listar_propostas()}  # todos os status
    with _batch_lock:
        _batch.update(status="running", total=len(ids), done=0, ok=0, itens=[], msg="")
    for pid in ids:
        prop = por_id.get(str(pid))
        item = {"projeto_id": pid, "titulo": (prop or {}).get("titulo", ""), "status": "", "ok": False}
        try:
            if prop is None:
                raise RuntimeError("proposta não encontrada no cache")
            ok, msg = _avaliar_um(str(pid), prop)
            item.update(ok=ok, status=msg)
        except Exception as e:  # noqa: BLE001
            item.update(ok=False, status=str(e)[:120])
        with _batch_lock:
            _batch["itens"].append(item)
            _batch["done"] += 1
            if item["ok"]:
                _batch["ok"] += 1
    with _batch_lock:
        _batch["status"] = "done"
        _batch["msg"] = f"{_batch['ok']}/{_batch['total']} avaliadas."


@app.route("/propostas/avaliar", methods=["POST"])
def propostas_avaliar():
    """Dispara avaliação em lote. Corpo JSON: {ids:[...]} ou {pendentes:true}."""
    body = request.get_json(silent=True) or {}
    filtro = body.get("status") or [STATUS_PRESTACAO]
    props = sigfapes.listar_propostas(status=filtro)
    avaliados = {str(m.get("projeto_id") or "") for m in store.listar() if m.get("projeto_id")}
    if body.get("pendentes"):
        ids = [sigfapes.projeto_id_do_protocolo(p["protocolo"]) for p in props]
        ids = [i for i in ids if i and i not in avaliados]
    else:
        ids = [str(i) for i in (body.get("ids") or []) if str(i)]
    if not ids:
        return jsonify({"erro": "Nenhuma proposta pendente/selecionada."}), 400
    with _batch_lock:
        if _batch["status"] == "running":
            return jsonify(_batch), 202
        _batch.update(status="running", total=len(ids), done=0, ok=0, itens=[], msg="")
    threading.Thread(target=_run_batch, args=(ids,), daemon=True).start()
    return jsonify({"status": "running", "total": len(ids)}), 202


@app.route("/propostas/avaliar_status")
def propostas_avaliar_status():
    with _batch_lock:
        return jsonify(_batch)


@app.route("/propostas/sync_status")
def propostas_sync_status():
    import os as _os
    with _sync_lock:
        estado = dict(_sync)
    # Progresso aproximado: tamanho do arquivo parcial sendo baixado (sem total
    # conhecido — o SIGFAPES não envia Content-Length).
    import glob
    baixado = 0
    partes = glob.glob(sigfapes.CSV_CACHE + ".part*")
    if partes:
        baixado = max(_os.path.getsize(p) for p in partes)
    elif _os.path.exists(sigfapes.CSV_CACHE):
        baixado = _os.path.getsize(sigfapes.CSV_CACHE)
    estado["bytes"] = baixado
    estado["mb"] = round(baixado / 1048576, 1)
    return jsonify(estado)


@app.route("/")
@app.route("/propostas")
def propostas_endpoint():
    """Página principal: propostas do SIGFAPES (em prestação, por edital) + a avaliação
    de cada uma inline (nota, situação, parecer, PDF) quando já avaliada.

    Lê o cache baixado por `sigfapes.baixar_propostas_csv` (CLI/botão Sincronizar).
    """
    import os as _os
    tem_cache = _os.path.exists(sigfapes.CSV_CACHE)
    grupos, total = [], 0
    avaliadas = aprovadas = 0
    notas = []
    status_opcoes = []
    # Filtros combináveis (AND): status (multi) + edital (multi) + busca + avaliação.
    # Sem status selecionado = TODAS as propostas (padrão mostra tudo).
    status_sel = [s for s in request.args.getlist("status") if s.strip()]
    edital_sel = [e for e in request.args.getlist("edital") if e.strip()]
    q = (request.args.get("q") or "").strip()
    aval_sel = (request.args.get("avaliacao") or "").strip()  # ''|avaliadas|pendentes
    status_opcoes = sigfapes.status_disponiveis()  # lista canônica CONTRATADO (safe)
    edital_opcoes = sigfapes.editais_disponiveis()
    if tem_cache:
        props = sigfapes.listar_propostas(status=status_sel)
        # Filtro por edital (AND).
        if edital_sel:
            sel = set(edital_sel)
            props = [p for p in props if p["edital"] in sel]
        # Busca textual (AND) em título, pesquisador e protocolo.
        if q:
            ql = q.casefold()
            props = [p for p in props if ql in (p["titulo"] + " " + p["pesquisador"]
                                                + " " + p["protocolo"]).casefold()]
        # Anexa avaliação a cada proposta.
        por_projeto = {str(m.get("projeto_id") or ""): m for m in store.listar()
                       if m.get("projeto_id")}
        for p in props:
            pid = sigfapes.projeto_id_do_protocolo(p["protocolo"])
            p["projeto_id"] = pid
            p["aval"] = por_projeto.get(pid)
        # Filtro por situação da avaliação (AND).
        if aval_sel == "avaliadas":
            props = [p for p in props if p["aval"]]
        elif aval_sel == "pendentes":
            props = [p for p in props if not p["aval"]]
        for p in props:
            if p["aval"]:
                avaliadas += 1
                if p["aval"].get("situacao") == "APROVADO":
                    aprovadas += 1
                if isinstance(p["aval"].get("nota"), (int, float)):
                    notas.append(p["aval"]["nota"])
        total = len(props)
        grupos = sigfapes.agrupar_por_edital(props)
    media = round(sum(notas) / len(notas)) if notas else 0
    reprovadas = avaliadas - aprovadas
    return render_template(
        "propostas.html",
        grupos=grupos, total=total, tem_cache=tem_cache,
        status_opcoes=status_opcoes, status_sel=status_sel,
        edital_opcoes=edital_opcoes, edital_sel=edital_sel, q=q, aval_sel=aval_sel,
        avaliadas=avaliadas, aprovadas=aprovadas, reprovadas=reprovadas,
        media=media, limiar=store.LIMIAR_APROVACAO,
    )


@app.route("/propostas/<projeto_id>")
def proposta_detalhe(projeto_id):
    """Página de uma proposta: dados + PDF do projeto + avaliação (se houver)."""
    prop = sigfapes.proposta_por_projeto_id(projeto_id)
    if prop is None:
        abort(404)
    # Avaliação vinculada a este projeto_id (quando já avaliado).
    aval = None
    for m in store.listar():
        if str(m.get("projeto_id") or "") == str(projeto_id):
            aval = m
            break
    # Documentos da prestação (Informações → Projeto Contratado → Documentos).
    documentos, tem_relatorio = [], False
    try:
        documentos = sigfapes.listar_documentos_prestacao(projeto_id)
        tem_relatorio = any(sigfapes._RE_RELATORIO.search(d["nome"])
                            or sigfapes._RE_RELATORIO.search(d["descricao"])
                            for d in documentos)
    except Exception:  # noqa: BLE001 — sem acesso/sessão, página ainda renderiza
        pass
    return render_template("proposta.html", p=prop, projeto_id=projeto_id, aval=aval,
                           documentos=documentos, tem_relatorio=tem_relatorio)


@app.route("/propostas/<projeto_id>/relatorio.pdf")
def proposta_relatorio_pdf(projeto_id):
    """Baixa/serve o relatório técnico (Anexo VI) da prestação, cacheado."""
    try:
        caminho = sigfapes.baixar_relatorio_pdf(projeto_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erro": str(e)}), 502
    return send_file(caminho, mimetype="application/pdf",
                     download_name=f"relatorio_tecnico_{projeto_id}.pdf")


@app.route("/propostas/<projeto_id>/anexo/<file_id>")
def proposta_anexo(projeto_id, file_id):
    """Baixa/serve um anexo da prestação (contratados/downloadanexo.php)."""
    import os as _os
    if not file_id.isdigit():
        abort(404)
    destino = _os.path.join(sigfapes._REL_PDF_DIR, f"anexo_{file_id}.pdf")
    try:
        caminho = sigfapes.baixar_anexo(file_id, destino)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erro": str(e)}), 502
    return send_file(caminho, mimetype="application/pdf",
                     download_name=f"anexo_{file_id}.pdf")


@app.route("/propostas/<projeto_id>/projeto.pdf")
def proposta_projeto_pdf(projeto_id):
    """Baixa/serve o PDF do projeto (proxy autenticado do SIGFAPES, cacheado).
    O nome do arquivo inclui o status (situação) da proposta."""
    import re
    try:
        caminho = sigfapes.baixar_projeto_pdf(projeto_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erro": str(e)}), 502
    prop = sigfapes.proposta_por_projeto_id(projeto_id) or {}
    situ = re.sub(r"[^\wÀ-ÿ -]", "", (prop.get("situacao") or "")).strip().replace(" ", "_")
    nome = f"projeto_{projeto_id}" + (f"_{situ}" if situ else "") + ".pdf"
    return send_file(caminho, mimetype="application/pdf", download_name=nome)


@app.route("/projetos")
def projetos_endpoint():
    """Compat: a lista de avaliados foi unificada na página /propostas."""
    from flask import redirect
    return redirect("/propostas", code=302)


@app.route("/projetos/<aval_id>")
def projeto_resultado(aval_id):
    """Página do resultado de uma avaliação (parecer técnico em HTML)."""
    resultado = store.carregar(aval_id)
    if resultado is None:
        abort(404)
    meta = store._meta(aval_id) or {}
    titulo = meta.get("titulo") or "Prestação de Contas Técnica"
    return Response(gerar_html(resultado, titulo=titulo), mimetype="text/html")


@app.route("/projetos/<aval_id>/pdf")
def projeto_pdf(aval_id):
    """Baixa o PDF do parecer (gerado sob demanda e cacheado)."""
    try:
        caminho = store.pdf_path(aval_id)
    except RuntimeError as e:
        return jsonify({"erro": str(e)}), 502
    if caminho is None:
        abort(404)
    meta = store._meta(aval_id) or {}
    nome = (meta.get("titulo") or "parecer").replace(" ", "_")
    return send_file(caminho, mimetype="application/pdf",
                     as_attachment=True, download_name=f"parecer_{nome}.pdf")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
