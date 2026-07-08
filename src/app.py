"""POC web: avaliação técnica de prestação de contas (FAPES/IFES) via Mistral."""
import os

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

from analyzer import analisar
from extract import extract_many
from report import gerar_html

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB por requisição


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analisar", methods=["POST"])
def analisar_endpoint():
    projeto_files = request.files.getlist("projeto")
    prestacao_files = request.files.getlist("prestacao")

    if not projeto_files or not prestacao_files:
        return jsonify({"erro": "Envie ao menos um arquivo de projeto e um de prestação."}), 400

    try:
        projeto_texto = extract_many(projeto_files)
        prestacao_texto = extract_many(prestacao_files)
    except ValueError as e:
        return jsonify({"erro": f"Falha ao ler arquivos: {e}"}), 400

    try:
        resultado = analisar(projeto_texto, prestacao_texto)
    except (RuntimeError, ValueError) as e:
        return jsonify({"erro": str(e)}), 502

    return jsonify(resultado)


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
