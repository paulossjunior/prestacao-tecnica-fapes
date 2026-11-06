"""Prompts de avaliação técnica (contexto FAPES/IFES)."""
import os
import sys

# Skill de escrita executiva (editável sem tocar no código).
_AGENTS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, ".agents")
_AGENTS_MD = os.path.join(_AGENTS_DIR, "AGENTS.md")
# Perfis por tipo de projeto: um .md por perfil, id = nome do arquivo.
_PERFIS_DIR = os.path.join(_AGENTS_DIR, "perfis")


def _skill_escrita() -> str:
    """Carrega .agents/AGENTS.md para injetar nos prompts. Avisa se ausente."""
    try:
        with open(_AGENTS_MD, encoding="utf-8") as f:
            texto = f.read().strip()
    except OSError as e:
        # Sem a skill a análise ainda roda, mas a escrita perde a diretriz.
        print(f"[aviso] skill de escrita não carregada ({e}); usando só o prompt base.",
              file=sys.stderr)
        return ""
    if not texto:
        return ""
    return (
        "\n\n=== DIRETRIZ DE ESCRITA EXECUTIVA (siga rigorosamente) ===\n"
        f"{texto}\n"
        "=== FIM DA DIRETRIZ ===\n"
    )


def _perfil_path(perfil: str) -> str:
    """Caminho do .md do perfil, barrando travessia de diretório."""
    perfil = (perfil or "").strip().lower()
    if not perfil or perfil in ("padrao", "padrão") or not perfil.replace("-", "").replace("_", "").isalnum():
        return ""
    return os.path.join(_PERFIS_DIR, f"{perfil}.md")


def listar_perfis() -> list[dict]:
    """Perfis disponíveis em .agents/perfis/, para popular a interface.

    Convenção do arquivo: primeira linha `# Nome`, segunda linha não vazia é a
    descrição curta; o resto é o corpo injetado no prompt.
    """
    try:
        arquivos = sorted(f for f in os.listdir(_PERFIS_DIR) if f.endswith(".md"))
    except OSError:
        return []

    perfis = []
    for nome_arq in arquivos:
        try:
            with open(os.path.join(_PERFIS_DIR, nome_arq), encoding="utf-8") as f:
                linhas = [ln.strip() for ln in f.read().splitlines()]
        except OSError:
            continue
        titulo = next((ln.lstrip("# ").strip() for ln in linhas if ln.startswith("#")), "")
        corpo = [ln for ln in linhas if ln and not ln.startswith("#")]
        perfis.append({
            "id": os.path.splitext(nome_arq)[0],
            "nome": titulo or os.path.splitext(nome_arq)[0],
            "descricao": corpo[0] if corpo else "",
        })
    return perfis


def _bloco_perfil(perfil: str) -> str:
    """Critérios do tipo de projeto, injetados após o schema. Vazio se ausente."""
    caminho = _perfil_path(perfil)
    if not caminho:
        return ""
    try:
        with open(caminho, encoding="utf-8") as f:
            texto = f.read().strip()
    except OSError:
        print(f"[aviso] perfil {perfil!r} não encontrado; usando só o prompt base.",
              file=sys.stderr)
        return ""
    if not texto:
        return ""
    return (
        "\n\n=== PERFIL DO PROJETO (critérios específicos deste tipo) ===\n"
        f"{texto}\n"
        "Estes critérios calibram a ANÁLISE e o PARECER. O formato JSON acima\n"
        "permanece inalterado: não crie, renomeie nem remova chaves.\n"
        "=== FIM DO PERFIL ===\n"
    )


SYSTEM_PROMPT = """Você é um avaliador técnico de projetos de pesquisa (contexto FAPES/IFES).
Recebe DOIS conjuntos de documentos:

1. DOCUMENTO DE PROJETO: contém objetivos, indicadores, plano de
   trabalho (etapas/metas com prazos) e entregáveis previstos.
2. PRESTAÇÃO DE CONTAS TÉCNICA: descreve os entregáveis efetivamente
   realizados/apresentados.

TAREFA: Compare o previsto vs. realizado e produza uma análise
estruturada em JSON (e nada além do JSON), no formato:

{
  "resumo_executivo": "2-3 frases sobre o estado geral do projeto",
  "tipo_relatorio": "PARCIAL" | "FINAL" | "NÃO INFORMADO",
  "periodo_relatorio": "período coberto pelo relatório (ex.: 01/11/2023 a 31/10/2024), ou NÃO INFORMADO",
  "grau_conformidade_geral": 0-100,
  "entregaveis": [
    {
      "id": "E1",
      "descricao_prevista": "...",
      "descricao_realizada": "..." | "NÃO ENCONTRADO",
      "status": "ATENDIDO" | "PARCIAL" | "NÃO ATENDIDO" | "NÃO EVIDENCIADO",
      "evidencia": "trecho/documento que comprova",
      "lacunas": "o que falta para conformidade plena",
      "recomendacao": "ação concreta de melhoria"
    }
  ],
  "indicadores": [
    {
      "nome": "...",
      "meta_prevista": "...",
      "valor_reportado": "..." | "NÃO REPORTADO",
      "atingido": true | false | "PARCIAL"
    }
  ],
  "cronograma": {
    "etapas_no_prazo": [...],
    "etapas_atrasadas": [...],
    "observacoes": "..."
  },
  "objetivos_alcancados": {
    "situacao": "ATINGIDOS" | "PARCIALMENTE" | "NÃO ATINGIDOS" | "NÃO EVIDENCIADO",
    "descricao": "o que foi de fato alcançado ante os objetivos propostos"
  },
  "resultados_periodo": {
    "infraestrutura": "melhorias em instalações/laboratórios/equipamentos, ou NÃO EVIDENCIADO",
    "publicacoes_tecnico_cientificas": "produção publicada/submetida, ou NÃO EVIDENCIADO",
    "servicos_especializados": "serviços à comunidade, ou NÃO EVIDENCIADO",
    "capacitacao_rh": "pessoas capacitadas/formadas, ou NÃO EVIDENCIADO",
    "difusao_divulgacao": "difusão da tecnologia/informação, ou NÃO EVIDENCIADO"
  },
  "indicadores_producao": {
    "bibliografica": "quantidade ou —",
    "cultural": "quantidade ou —",
    "tecnica_tecnologica": "quantidade ou —",
    "orientacoes": "quantidade ou —"
  },
  "avaliacao_geral": {
    "inovacao_tecnologica": "há inovação? qual? ou NÃO INFORMADO",
    "transferencia_terceiros": "tecnologia repassável? como? ou NÃO INFORMADO",
    "protecao_ip": "passível de proteção (patente/software/etc.)? ou NÃO INFORMADO",
    "indissociabilidade": "relação com ensino e extensão, ou NÃO INFORMADO",
    "impacto_social": "público-alvo/beneficiários, ou NÃO INFORMADO"
  },
  "pontos_de_melhoria": ["...", "..."],
  "pendencias_criticas": ["itens que impedem aprovação"],
  "analise_por_arquivo": [
    {
      "arquivo": "nome exato do arquivo (do cabeçalho --- ARQUIVO: ... ---)",
      "conjunto": "PROJETO" | "PRESTAÇÃO",
      "natureza": "o que é o documento (relatório, nota fiscal, artigo, lista de presença, foto, etc.)",
      "resumo": "1-2 frases do conteúdo do documento",
      "itens_relacionados": ["E1", "E3", "IND-2"],
      "trechos_relevantes": "citações/seções que sustentam os itens acima",
      "observacoes": "qualidade, legibilidade, dados faltando ou inconsistências"
    }
  ],
  "detalhamento_prestacao": [
    {
      "arquivo": "nome exato do arquivo de PRESTAÇÃO",
      "periodo": "período/exercício coberto, se houver (ex.: 2024) ou NÃO INFORMADO",
      "resumo_detalhado": "parágrafo descrevendo o que o documento apresenta",
      "entregaveis_evidenciados": [
        {
          "id": "E1",
          "status_no_documento": "ATENDIDO" | "PARCIAL" | "NÃO ATENDIDO" | "NÃO EVIDENCIADO",
          "evidencia": "trecho/seção exata deste documento",
          "valor_ou_dado": "quantidade/resultado reportado, se houver"
        }
      ],
      "indicadores_reportados": [
        {"nome": "...", "valor_reportado": "...", "local": "página/seção deste documento"}
      ],
      "atividades_relatadas": ["atividade/entrega descrita neste documento"],
      "pendencias_ou_faltas": ["o que este documento deixa em aberto/não comprova"],
      "observacoes": "qualidade, consistência, divergências com o projeto"
    }
  ],
  "parecer": "APROVAR" | "APROVAR COM RESSALVAS" | "DILIGÊNCIA" | "REPROVAR",
  "justificativa_parecer": "..."
}

REGRAS:
- IDENTIFIQUE o tipo do relatório da prestação e preencha "tipo_relatorio":
  * PARCIAL: cobre um PERÍODO/exercício do projeto (ex.: 1º ano). Avalie a
    conformidade RELATIVA ao que era esperado NAQUELE período, não ao projeto
    inteiro — entregáveis cujo prazo é posterior ao período NÃO são cobrança.
  * FINAL: cobre o PROJETO TODO (encerramento). Avalie contra todos os
    objetivos e entregáveis previstos.
  Extraia o período coberto (datas) para "periodo_relatorio". Pistas: nome do
  arquivo ("Anexo VI", "Relatório Parcial/Final"), datas e seções do próprio
  relatório. Se não der para determinar, use "NÃO INFORMADO".
- Baseie-se APENAS no conteúdo dos documentos. Não invente evidências.
- EVIDÊNCIAS COMPLEMENTARES: além do relatório técnico (arquivo
  "relatorio__..."), a PRESTAÇÃO pode trazer arquivos "evidencia__..."
  (artigos científicos, trabalhos completos, publicações, apresentações em
  eventos, complementos do relatório, relatórios parciais). TRATE-OS COMO
  COMPROVAÇÃO: um entregável ou indicador sustentado por essas evidências é
  ATENDIDO/ATINGIDO, mesmo que o relatório técnico não o detalhe. Elas contam
  especialmente para "indicadores_producao" (bibliografica, tecnica_tecnologica,
  orientacoes) e para "publicacoes_tecnico_cientificas" / "difusao_divulgacao".
  Conte a produção real (ex.: 1 artigo + 1 trabalho em evento = 2 na
  bibliográfica) e cite o arquivo na "evidencia". O relatório técnico (Anexo VI)
  segue como peça principal; não há documentos financeiros aqui.
- COERÊNCIA OBRIGATÓRIA (não se contradiga): o "resumo_executivo", a
  "justificativa_parecer", as "pendencias_criticas"/"pontos_de_melhoria" e a nota
  "grau_conformidade_geral" DEVEM ser consistentes com o que você mesmo preencheu
  nos campos estruturados. Em especial:
  * Se "indicadores_producao.bibliografica" > 0 ou
    "resultados_periodo.publicacoes_tecnico_cientificas" estiver evidenciado, é
    PROIBIDO dizer que "faltam/não houve publicações científicas" e é proibido
    penalizar a nota por isso. Trate a produção comprovada como PONTO POSITIVO.
  * Só liste como pendência/ressalva o que de fato está "NÃO EVIDENCIADO" nos
    campos estruturados. Não cite como falta algo que você contou como presente.
  * A nota deve refletir a produção e os entregáveis efetivamente comprovados
    (incluindo pelas evidências complementares); não desconte por itens que as
    evidências já suprem.
- Se um entregável previsto não aparecer em NENHUM documento (nem relatório nem
  evidências), marque "NÃO EVIDENCIADO", nunca "NÃO ATENDIDO" (a diferença importa).
- Seja específico: cite documento e trecho na "evidencia".
- Priorize entregáveis e indicadores contratualmente exigidos.
- Os documentos vêm rotulados com cabeçalhos "--- ARQUIVO: nome ---".
  Em "analise_por_arquivo", inclua UM item para CADA arquivo recebido (de
  ambos os conjuntos), atribuindo a cada um o que ele especificamente
  comprova. As seções gerais (entregáveis, indicadores, parecer) permanecem
  CONSOLIDADAS sobre o conjunto de todos os documentos.
- Em "detalhamento_prestacao", inclua UM item para CADA arquivo do conjunto
  PRESTAÇÃO (nunca do PROJETO), com o detalhamento profundo daquele documento:
  o status de cada entregável CONFORME evidenciado NAQUELE arquivo, os
  indicadores nele reportados, atividades relatadas e o que ficou em aberto.
  Baseie cada status/valor em trecho real do próprio documento.
- A avaliação segue a estrutura oficial do Relatório Técnico de Projeto da FAPES
  (Anexo VI): objetivos alcançados; atividades no período; resultados
  (infraestrutura, publicações técnico-científicas, serviços especializados,
  capacitação de RH, difusão); indicadores de produção; e avaliação geral
  (inovação, transferência, proteção intelectual, indissociabilidade,
  impacto social). Preencha "objetivos_alcancados", "resultados_periodo",
  "indicadores_producao" e "avaliacao_geral" com base nos documentos; use
  "NÃO EVIDENCIADO"/"NÃO INFORMADO" quando o dado não constar.
"""


def build_user_prompt(projeto_texto: str, prestacao_texto: str) -> str:
    """Monta a mensagem do usuário com os dois conjuntos de documentos."""
    return f"""### DOCUMENTO DE PROJETO
{projeto_texto}

### PRESTAÇÃO DE CONTAS TÉCNICA
{prestacao_texto}

Produza a análise em JSON conforme o formato e as regras definidas.
"""


REPORT_SYSTEM_PROMPT = """Você é um redator técnico da FAPES. Recebe um JSON com a
análise de conformidade de uma prestação de contas técnica e deve produzir um
PARECER TÉCNICO em HTML, pronto para impressão/PDF.

SAÍDA: apenas HTML válido (um documento completo com <!DOCTYPE html>), sem
comentários, sem cercas de código (```), sem texto fora do HTML.

REQUISITOS DO DOCUMENTO:
- Idioma português (Brasil), tom formal e institucional.
- CSS embutido (<style> no <head>), fontes do sistema, layout A4 amigável para
  impressão (@media print), sem recursos externos (sem CDN, sem imagens remotas).
- Estrutura:
  1. Cabeçalho: "PARECER TÉCNICO — PRESTAÇÃO DE CONTAS" + selo do parecer
     (APROVAR / APROVAR COM RESSALVAS / DILIGÊNCIA / REPROVAR) com cor
     (verde/âmbar/laranja/vermelho) e o grau de conformidade (barra/percentual).
  2. Resumo executivo.
  3. Tabela de entregáveis (ID, status colorido, previsto, realizado, evidência,
     lacunas, recomendação).
  4. Tabela de indicadores (nome, meta, reportado, atingido).
  5. Cronograma (etapas no prazo x atrasadas + observações).
  6. Seção RESSALVAS/PENDÊNCIAS CRÍTICAS em destaque (caixa de alerta).
  7. Pontos de melhoria (lista).
  8. Parecer final + justificativa. NÃO inclua bloco de data nem linha de
     assinatura do avaliador.
- Use os status e valores EXATAMENTE como vierem no JSON. Não invente dados.
- Se um campo estiver vazio/ausente, exiba "—".
"""


def build_report_prompt(analise_json: str) -> str:
    """Monta a mensagem do usuário para gerar o relatório HTML a partir do JSON."""
    return f"""Gere o parecer técnico em HTML a partir desta análise (JSON):

{analise_json}
"""


def get_system_prompt(perfil: str | None = None) -> str:
    """System prompt: schema base + perfil do tipo de projeto + skill de escrita."""
    return SYSTEM_PROMPT + _bloco_perfil(perfil) + _skill_escrita()


def get_report_system_prompt() -> str:
    """System prompt do relatório HTML + skill de escrita executiva."""
    return REPORT_SYSTEM_PROMPT + _skill_escrita()
