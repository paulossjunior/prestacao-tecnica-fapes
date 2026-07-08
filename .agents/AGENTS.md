# Skill — Escrita de Relatório Executivo (Parecer Técnico FAPES/IFES)

Guia de estilo carregado em runtime pelos prompts (`src/prompts.py`) e injetado
na geração do **resumo executivo** e do **relatório HTML**. Editar este arquivo
melhora a qualidade da escrita sem alterar código.

## Objetivo

Produzir texto que um **gestor/avaliador decide em 30 segundos**: o que foi
entregue, o que falta, e qual a decisão. Sem jargão vazio, sem enrolação.

## Princípios (nesta ordem)

1. **BLUF — Bottom Line Up Front.** Primeira frase = veredito + número.
   Ex.: "Projeto em conformidade parcial (75%); recomenda-se APROVAR COM
   RESSALVAS, condicionado a 3 pendências."
2. **Quantifique sempre.** "3 de 5 estações", "1 de 4 artigos", "uptime 88% vs.
   meta 95%". Número supera adjetivo. Nunca "avançou significativamente" sozinho.
3. **Previsto vs. realizado, lado a lado.** Toda afirmação de entrega compara com
   a meta contratada. Sem meta citada, a frase não fecha.
4. **Evidência ancorada.** Cite documento e trecho ("Relatório Técnico, Seção
   3.2"). Sem fonte = não afirme; marque como NÃO EVIDENCIADO.
5. **Ressalvas em destaque, acionáveis.** Cada ressalva/pendência = o que falta +
   ação concreta + (se possível) prazo. Verbo no infinitivo: "Concluir…",
   "Submeter…", "Migrar…". Nunca ressalva genérica ("melhorar a gestão").
6. **Separe fato de juízo.** Primeiro o dado (o que os documentos dizem), depois a
   avaliação. Não misture opinião com evidência.

## Estrutura do resumo executivo (2–4 frases)

1. Veredito + grau de conformidade (número).
2. 1–2 pontos fortes concretos (quantificados).
3. 1–2 lacunas críticas que sustentam as ressalvas.
4. (Opcional) condição objetiva para aprovação plena.

## Tom e forma

- Português formal institucional, 3ª pessoa, voz ativa. Frases curtas (≤ 25
  palavras). Um parágrafo = uma ideia.
- Impessoal: "Recomenda-se", "Constatou-se", "Não foram apresentadas evidências".
- **Proibido:** "excelente", "ótimo", "conforme esperado" sem dado; "etc.";
  promessas futuras como se fossem entregas ("será implementado" ≠ entregue).
- Escala de status coerente: ATENDIDO / PARCIAL / NÃO ATENDIDO / NÃO EVIDENCIADO.
  NÃO EVIDENCIADO (não apareceu) ≠ NÃO ATENDIDO (apareceu e falhou).

## Escala do parecer (calibra o tom)

- **APROVAR** — conformidade alta, sem pendências que impeçam aceite.
- **APROVAR COM RESSALVAS** — entregas essenciais atendidas; pendências sanáveis,
  listadas e acionáveis.
- **DILIGÊNCIA** — faltam evidências/esclarecimentos para decidir; peça itens
  específicos.
- **REPROVAR** — descumprimento material do objeto/contrato.

## Teste final (auto-checagem antes de fechar)

- [ ] Primeira frase entrega veredito + número?
- [ ] Toda entrega comparada à meta contratada?
- [ ] Cada ressalva tem ação concreta?
- [ ] Zero adjetivo sem dado que o sustente?
- [ ] Nenhum dado inventado além dos documentos?
