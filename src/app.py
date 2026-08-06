"""POC web: avaliação técnica de prestação de contas (FAPES/IFES) via Mistral."""
import os
import threading
import uuid

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

from analyzer import analisar
from extract import extract_pairs
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
        _set(job_id, status="done", resultado=resultado)
    except Exception as e:  # noqa: BLE001 — devolve a mensagem ao cliente
        _set(job_id, status="error", erro=str(e))


@app.route("/")
def index():
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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
