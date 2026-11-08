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


# Evidências complementares: nº máximo de docs e teto de bytes por doc (evita
# OCR dispendioso em arquivos enormes). Produção técnica que comprova entregáveis.
_MAX_EVIDENCIAS = 6
_EVIDENCIA_MAX_BYTES = 9_000_000

# Estabilização da nota: roda a análise N vezes por documento e usa a MEDIANA das
# notas (reduz a variância do LLM que, perto do limiar, vira aprova/reprova por
# ruído). Reaproveita o texto OCR, então o custo extra é só das chamadas ao LLM.
# Ajustável por env AVAL_AMOSTRAS (1 = sem repetição).
try:
    _AVAL_AMOSTRAS = max(1, int(os.getenv("AVAL_AMOSTRAS", "3")))
except (TypeError, ValueError):
    _AVAL_AMOSTRAS = 3


import re as _re_perfil
# Detecta o perfil de avaliação pelo edital/título (deixa de usar "inovacao" fixo,
# que penalizava projetos de pesquisa com critérios de IP/transferência).
_RE_PERFIL_INOV = _re_perfil.compile(
    r"inova|tecnol|plataforma|software|conectafapes|pappe|tecnova|startup", _re_perfil.I)
_RE_PERFIL_EXT = _re_perfil.compile(r"extens[aã]o|populariza|divulga", _re_perfil.I)


def _perfil_do_projeto(prop) -> str:
    """Perfil ('pesquisa' | 'inovacao' | 'extensao') pelo edital/título. Default
    pesquisa (maioria dos editais FAPES é pesquisa/iniciação científica)."""
    txt = f"{(prop or {}).get('edital','')} {(prop or {}).get('titulo','')}"
    if _RE_PERFIL_INOV.search(txt):
        return "inovacao"
    if _RE_PERFIL_EXT.search(txt):
        return "extensao"
    return "pesquisa"


def _analisar_estavel(projtxt, prest, perfil, n=None):
    """Roda `analisar` n vezes e devolve UM resultado com a nota = mediana das
    notas das rodadas (representante = rodada cuja nota é a mais próxima da
    mediana, p/ o texto casar com o número). n=1 equivale a uma única rodada."""
    import statistics
    n = _AVAL_AMOSTRAS if n is None else max(1, n)
    rodadas = []
    for _ in range(n):
        try:
            rodadas.append(analisar(projtxt, prest, perfil=perfil))
        except Exception:  # noqa: BLE001 — uma rodada ruim não aborta a estabilização
            continue
    if not rodadas:
        return analisar(projtxt, prest, perfil=perfil)  # deixa o erro propagar
    notas = [r.get("grau_conformidade_geral") for r in rodadas
             if isinstance(r.get("grau_conformidade_geral"), (int, float))]
    if not notas:
        return rodadas[-1]
    med = statistics.median(notas)
    rep = min((r for r in rodadas if isinstance(r.get("grau_conformidade_geral"), (int, float))),
              key=lambda r: abs(r["grau_conformidade_geral"] - med))
    # Guarda o histórico das notas amostradas (registro da estabilização).
    rep["notas_amostras"] = [round(x) for x in notas]
    rep["nota_mediana"] = round(med)
    rep["grau_conformidade_geral"] = round(med)
    return rep


def _slug(texto: str) -> str:
    """Nome de arquivo seguro a partir do nome do documento (p/ rótulo no LLM)."""
    import re as _re
    s = _re.sub(r"[^\w]+", "_", (texto or "").strip())[:50].strip("_")
    return s or "doc"


def _coletar_evidencias(projeto_id, destino_dir):
    """Baixa as evidências complementares (artigos, trabalhos, complementos) numa
    pasta e devolve (texto_extraído, [nomes_incluídos]). Vazio se não houver."""
    import os as _os
    import ocr
    evid = sigfapes.listar_evidencias_complementares(projeto_id)
    incluidos = []
    for doc in evid[:_MAX_EVIDENCIAS]:
        # file id no nome evita colisão quando dois anexos têm nomes iguais
        # (ex.: "Cópia Artigo" x2): sem isso, baixar_anexo pularia o 2º (arquivo já
        # existe) e o 1º seria contado duas vezes.
        alvo = _os.path.join(destino_dir, f"evidencia__{_slug(doc.get('nome'))}__{doc.get('file')}.pdf")
        try:
            sigfapes.baixar_anexo(doc["file"], alvo)
            if _os.path.getsize(alvo) > _EVIDENCIA_MAX_BYTES:
                _os.remove(alvo)  # grande demais p/ OCR — ignora
                continue
            incluidos.append(doc.get("nome", doc["file"]))
        except Exception:  # noqa: BLE001 — evidência ruim não aborta a avaliação
            if _os.path.exists(alvo):
                _os.remove(alvo)
    if not incluidos:
        return "", []
    return ocr.extract_folder_auto(destino_dir), incluidos


def _avaliar_um(projeto_id, prop):
    """Avalia uma proposta: baixa o projeto e AVALIA CADA RELATÓRIO (Anexo VI)
    separadamente (parcial por período / final), gerando uma avaliação por
    relatório (histórico). As EVIDÊNCIAS COMPLEMENTARES da prestação (artigos,
    trabalhos, complementos) entram como comprovação em todas as avaliações.
    Devolve (ok, msg)."""
    import os as _os
    import shutil
    import tempfile
    proj_pdf = sigfapes.baixar_projeto_pdf(projeto_id)
    relatorios = sigfapes.listar_relatorios(projeto_id)
    if not relatorios:
        raise RuntimeError(f"Relatório técnico (Anexo VI) não encontrado no projeto {projeto_id}.")
    titulo = (prop.get("titulo") or f"Projeto {projeto_id}")[:80]
    perfil = _perfil_do_projeto(prop)
    import ocr
    # Evidências complementares: baixa e extrai UMA vez (compartilhado entre os
    # relatórios), evitando re-OCR por relatório.
    with tempfile.TemporaryDirectory() as ed:
        evid_txt, evid_nomes = _coletar_evidencias(projeto_id, ed)
    if evid_nomes:
        print(f"[evidências] {projeto_id}: {len(evid_nomes)} doc(s) — "
              + ", ".join(n[:28] for n in evid_nomes), flush=True)
    # Agrupa relatórios multi-parte ("Anexo VI - final (1 de 3)"…): cada grupo é
    # UM documento lógico avaliado de uma vez (uma nota), não uma nota por parte.
    grupos = sigfapes.agrupar_relatorios(relatorios)
    notas, erros = [], []
    for grupo in grupos:
        rep = grupo[0]  # parte representativa (identidade do documento)
        nome_doc = sigfapes._RE_PARTE.sub("", rep.get("nome", "")).strip() or rep.get("nome", "")
        try:
            with tempfile.TemporaryDirectory() as d:
                _os.makedirs(_os.path.join(d, "projeto")); _os.makedirs(_os.path.join(d, "prestacao"))
                shutil.copy(proj_pdf, _os.path.join(d, "projeto"))
                for parte in grupo:  # todas as partes juntas = relatório completo
                    alvo = _os.path.join(d, "prestacao", f"relatorio__{parte['file']}.pdf")
                    sigfapes.baixar_anexo(parte["file"], alvo)
                projtxt = ocr.extract_folder_auto(_os.path.join(d, "projeto"))
                prest = ocr.extract_folder_auto(_os.path.join(d, "prestacao"))
            if evid_txt:
                prest += "\n\n" + evid_txt  # evidências já vêm rotuladas por arquivo
            resultado = _analisar_estavel(projtxt, prest, perfil)
            # O NOME do anexo é mais confiável que o palpite do modelo p/ parcial/final.
            tipo_nome = sigfapes.tipo_relatorio_por_nome(nome_doc, rep.get("descricao", ""))
            if tipo_nome:
                resultado["tipo_relatorio"] = tipo_nome
            elif len(grupos) == 1:
                # Único relatório do projeto e nome não diz "parcial/final": é o
                # relatório técnico do projeto todo → trata como FINAL.
                resultado["tipo_relatorio"] = "FINAL"
            tipo = resultado.get("tipo_relatorio", "") or ""
            suf = f" [{tipo.title()}]" if tipo and tipo != "NÃO INFORMADO" else ""
            # file id do documento = partes unidas, p/ deduplicar como um só doc.
            file_doc = "+".join(p.get("file", "") for p in grupo)
            store.salvar(resultado, titulo=titulo + suf, perfil=perfil, projeto_id=projeto_id,
                         relatorio_file=file_doc, relatorio_nome=nome_doc)
            notas.append(f"{tipo[:7] or '?'}:{resultado.get('grau_conformidade_geral')}")
        except Exception as e:  # noqa: BLE001 — um relatório ruim não aborta os outros
            erros.append(f"{nome_doc[:20]}: {str(e)[:40]}")
    if not notas:
        raise RuntimeError("nenhum relatório avaliado — " + "; ".join(erros))
    ev_sfx = f" +{len(evid_nomes)} evid." if evid_nomes else ""
    msg = f"{len(notas)}/{len(grupos)} relatório(s){ev_sfx} — " + " ".join(notas)
    if erros:
        msg += f" | {len(erros)} falha(s)"
    return True, msg


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


# Download em massa dos PDFs (projeto + documentos da prestação) para downloads/.
_DL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
_dl = {"status": "idle", "total": 0, "done": 0, "arquivos": 0, "msg": ""}
_dl_lock = threading.Lock()


def _baixar_pdfs_projeto(pid):
    """Baixa projeto + todos os documentos da prestação de um projeto para downloads/<pid>/."""
    import shutil
    destino = os.path.join(_DL_DIR, str(pid))
    os.makedirs(destino, exist_ok=True)
    n = 0
    try:
        proj = sigfapes.baixar_projeto_pdf(pid)
        shutil.copy(proj, os.path.join(destino, f"projeto_{pid}.pdf"))
        n += 1
    except Exception:  # noqa: BLE001
        pass
    try:
        docs = sigfapes.listar_documentos_prestacao(pid)
    except Exception:  # noqa: BLE001
        docs = []
    for d in docs:
        try:
            import re as _re
            nome = _re.sub(r"[^\wÀ-ÿ. -]", "", d.get("nome") or d["file"]).strip()[:50]
            alvo = os.path.join(destino, f"{d['file']}_{nome}.pdf")
            sigfapes.baixar_anexo(d["file"], alvo)
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def _run_download(ids):
    with _dl_lock:
        _dl.update(status="running", total=len(ids), done=0, arquivos=0, msg="")
    for pid in ids:
        try:
            n = _baixar_pdfs_projeto(pid)
        except Exception:  # noqa: BLE001
            n = 0
        with _dl_lock:
            _dl["done"] += 1
            _dl["arquivos"] += n
    with _dl_lock:
        _dl["status"] = "done"
        _dl["msg"] = f"{_dl['arquivos']} PDFs em downloads/ ({_dl['done']} projetos)."


@app.route("/propostas/baixar_pdfs", methods=["POST"])
def propostas_baixar_pdfs():
    """Baixa os PDFs (projeto + prestação) dos projetos filtrados/selecionados."""
    body = request.get_json(silent=True) or {}
    if body.get("ids"):
        ids = [str(i) for i in body["ids"] if str(i)]
    else:
        filtro = body.get("status") or [STATUS_PRESTACAO]
        ids = [sigfapes.projeto_id_do_protocolo(p["protocolo"])
               for p in sigfapes.listar_propostas(status=filtro)]
        ids = [i for i in ids if i]
    if not ids:
        return jsonify({"erro": "Nenhum projeto no filtro/seleção."}), 400
    with _dl_lock:
        if _dl["status"] == "running":
            return jsonify(_dl), 202
        _dl.update(status="running", total=len(ids), done=0, arquivos=0, msg="")
    threading.Thread(target=_run_download, args=(ids,), daemon=True).start()
    return jsonify({"status": "running", "total": len(ids)}), 202


@app.route("/propostas/baixar_status")
def propostas_baixar_status():
    with _dl_lock:
        return jsonify(_dl)


def _slug_arq(texto: str) -> str:
    """Nome de arquivo/pasta seguro (preserva acentos, troca o resto por _)."""
    import re as _re
    s = _re.sub(r"[^\wÀ-ÿ. -]+", "_", (texto or "").strip())[:50].strip("_ .")
    return s or "doc"


def _coletar_pdfs_projeto(pid, prop):
    """[(arcname, bytes)] com o projeto + relatório(s) técnico(s) + o(s) PDF(s) do
    parecer da avaliação (um por documento avaliado: cada parcial/final)."""
    import tempfile
    base = f"{pid}_{_slug_arq(prop.get('titulo'))}"
    out = []
    try:
        pj = sigfapes.baixar_projeto_pdf(pid)
        with open(pj, "rb") as f:
            out.append((f"{base}/projeto_{pid}.pdf", f.read()))
    except Exception:  # noqa: BLE001
        pass
    try:
        rels = sigfapes.listar_relatorios(pid)
    except Exception:  # noqa: BLE001
        rels = []
    for i, r in enumerate(rels, 1):
        try:
            with tempfile.TemporaryDirectory() as d:
                alvo = os.path.join(d, f"{r['file']}.pdf")
                sigfapes.baixar_anexo(r["file"], alvo)
                with open(alvo, "rb") as f:
                    out.append((f"{base}/relatorio_{i}_{_slug_arq(r.get('nome'))}.pdf", f.read()))
        except Exception:  # noqa: BLE001
            continue
    # Parecer CONSOLIDADO do projeto (veredito geral = final, senão último relatório).
    try:
        cons = store.pdf_path_projeto(pid, titulo=prop.get("titulo"))
        if cons and os.path.exists(cons):
            with open(cons, "rb") as f:
                out.append((f"{base}/parecer_PROJETO_consolidado.pdf", f.read()))
    except Exception:  # noqa: BLE001
        pass
    # Parecer da avaliação (gerado sob demanda e cacheado) — um por documento.
    try:
        docs = store.por_documento(pid)
    except Exception:  # noqa: BLE001
        docs = []
    for i, dc in enumerate(docs, 1):
        try:
            pdf = store.pdf_path(dc["id"])
            if not pdf or not os.path.exists(pdf):
                continue
            tipo = (dc.get("tipo_relatorio") or "aval")
            tipo = tipo.title() if tipo and tipo != "NÃO INFORMADO" else "aval"
            nota = dc.get("nota")
            with open(pdf, "rb") as f:
                out.append((f"{base}/parecer_{i}_{_slug_arq(tipo)}_{nota}pct.pdf", f.read()))
        except Exception:  # noqa: BLE001
            continue
    return out


@app.route("/propostas/baixar.zip")
def propostas_baixar_zip():
    """Baixa, no navegador, os PDFs (projeto + relatório técnico) dos projetos
    selecionados. 1 arquivo = PDF direto; mais de 1 = .zip."""
    import io
    import zipfile
    ids = [i.strip() for i in (request.args.get("ids") or "").split(",") if i.strip()]
    if not ids:
        abort(400, "Nenhum projeto selecionado.")
    try:
        por_id = {sigfapes.projeto_id_do_protocolo(p["protocolo"]): p
                  for p in sigfapes.listar_propostas()}
    except Exception:  # noqa: BLE001
        por_id = {}
    arquivos = []
    for pid in ids:
        arquivos.extend(_coletar_pdfs_projeto(pid, por_id.get(pid, {})))
    if not arquivos:
        abort(404, "Nenhum PDF disponível para a seleção.")
    if len(arquivos) == 1:
        nome, data = arquivos[0]
        return Response(data, mimetype="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(nome)}"'})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, data in arquivos:
            z.writestr(nome, data)
    fname = (f"prestacao_{ids[0]}.zip" if len(ids) == 1
             else f"prestacao_{len(ids)}_projetos.zip")
    return Response(buf.getvalue(), mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})


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
        por_projeto = store.por_projeto()  # projeto_id -> avaliação mais recente
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
        media=media, limiar=store.get_limiar(),
    )


@app.route("/config/limiar", methods=["POST"])
def config_limiar():
    """Define o percentual de aprovação (limiar). Recalcula a situação de todos."""
    valor = (request.form.get("limiar") or
             (request.get_json(silent=True) or {}).get("limiar"))
    try:
        novo = store.set_limiar(valor)
    except (TypeError, ValueError):
        return jsonify({"erro": "valor inválido"}), 400
    return jsonify({"limiar": novo})


@app.route("/analise")
def analise_por_edital():
    """Tela guiada: escolhe o edital, lista suas propostas, seleciona e avalia."""
    import os as _os
    tem_cache = _os.path.exists(sigfapes.CSV_CACHE)
    edital_sel = (request.args.get("edital") or "").strip()
    editais, propostas = [], []
    if tem_cache:
        editais = sigfapes.editais_disponiveis()
        if edital_sel:
            avaliados = store.por_projeto()  # projeto_id -> avaliação mais recente
            for p in sigfapes.listar_propostas():
                if p["edital"] != edital_sel:
                    continue
                pid = sigfapes.projeto_id_do_protocolo(p["protocolo"])
                p["projeto_id"] = pid
                p["aval"] = avaliados.get(pid)
                propostas.append(p)
    return render_template("analise.html", tem_cache=tem_cache, editais=editais,
                           edital_sel=edital_sel, propostas=propostas)


@app.route("/propostas/<projeto_id>")
def proposta_detalhe(projeto_id):
    """Página de uma proposta: dados + PDF do projeto + avaliação (se houver)."""
    prop = sigfapes.proposta_por_projeto_id(projeto_id)
    if prop is None:
        abort(404)
    # Avaliação por documento (um projeto tem vários parciais + final) + nota
    # geral (final, senão último relatório) + histórico completo.
    hist = store.historico(projeto_id)
    por_doc = store.por_documento(projeto_id)   # nota atual de cada documento
    resumo = store.resumo_projeto(projeto_id)   # nota geral (final/último relatório)
    aval = resumo                               # resumo é a "avaliação" do projeto
    # Documentos da prestação (Informações → Projeto Contratado → Documentos).
    documentos, tem_relatorio = [], False
    try:
        documentos = sigfapes.listar_documentos_prestacao(projeto_id)
        tem_relatorio = any(sigfapes._eh_relatorio_projeto(d) for d in documentos)
    except Exception:  # noqa: BLE001 — sem acesso/sessão, página ainda renderiza
        pass
    return render_template("proposta.html", p=prop, projeto_id=projeto_id, aval=aval,
                           resumo=resumo, por_doc=por_doc,
                           historico=hist, documentos=documentos, tem_relatorio=tem_relatorio)


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


@app.route("/propostas/<projeto_id>/parecer_projeto.pdf")
def proposta_parecer_consolidado(projeto_id):
    """PDF do parecer CONSOLIDADO do projeto por completo (veredito geral = final,
    senão último relatório + resumo do parecer de cada relatório)."""
    prop = sigfapes.proposta_por_projeto_id(projeto_id) or {}
    try:
        caminho = store.pdf_path_projeto(projeto_id, titulo=prop.get("titulo"))
    except Exception as e:  # noqa: BLE001
        return jsonify({"erro": str(e)}), 500
    if not caminho:
        abort(404, "Projeto sem avaliação para consolidar.")
    return send_file(caminho, mimetype="application/pdf",
                     download_name=f"parecer_projeto_{projeto_id}.pdf")


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
    return Response(gerar_html(resultado, titulo=titulo,
                               projeto_id=meta.get("projeto_id")),
                    mimetype="text/html")


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
