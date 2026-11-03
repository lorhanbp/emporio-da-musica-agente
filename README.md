# Melô — agente de atendimento da Empório da Música

Protótipo de um agente de atendimento por texto para a loja fictícia Empório da Música (Campo Grande/MS), feito para o desafio técnico de AI Engineer da Artefact. A **Melô** responde sobre produtos (preço, estoque, promoção), políticas da loja (pagamento, troca, frete, garantia), status de pedidos e devoluções, e recusa o que foge do escopo.

## Como rodar

Requisitos: Python 3.11+ e uma chave da API da Anthropic.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # preencha ANTHROPIC_API_KEY
python -m emporio           # conversa no terminal
```

Opções do CLI:

| flag | efeito |
|---|---|
| `--sessao nome` | guarda e retoma o histórico em `.sessions/nome.json` |
| `--verbose` | mostra cada ferramenta chamada e o resultado |
| `--transcricao arquivo.md` | salva a conversa em markdown |

Testes (não usam a API): `pytest -q`.
Conversas de exemplo: `python scripts/gerar_exemplos.py` (regrava `exemplos/*.md`).

Variáveis opcionais: `EMPORIO_MODEL` (padrão `claude-haiku-5-5`) e `EMPORIO_HOJE` (data de referência, veja "Suposições").

## Arquitetura

```
cliente ──► CLI ──► Agente (loop de function calling) ──► Claude
                         │                                   │
                         └── ferramentas (Python puro) ◄─────┘
                              ├─ buscar_produtos / detalhes_produto   → CSVs em memória
                              ├─ consultar_pedidos / avaliar_devolucao → CSVs + verificação de identidade
                              ├─ simular_pagamento                     → regras de pagamento e frete
                              ├─ consultar_politicas / horario_da_loja_agora → data/politicas.md
                              └─ encaminhar_para_humano                → .sessions/encaminhamentos.jsonl
```

## Decisões técnicas

**Function calling, sem RAG nem agente de SQL.** Os dados são minúsculos (65 produtos, 20 pedidos, 8 páginas de políticas). Um pipeline de embeddings seria complexidade sem ganho de qualidade, e um agente de SQL deixaria o modelo escrever consultas sobre dados de clientes. Com ferramentas tipadas, o modelo decide *qual* ferramenta chamar (é isso que o desafio chama de "saber quando consultar dados e quando consultar políticas") e o Python garante o resultado.

**Cálculo em código, texto no modelo.** Preço com promoção, PIX, parcela mínima, frete e prazos de devolução são calculados nas ferramentas. O LLM só escolhe a ferramenta e redige. Isso elimina uma classe inteira de alucinação numérica e deixa as regras testáveis (`tests/`).

**Políticas como ferramenta, não como prompt.** O PDF foi convertido para `data/politicas.md`, dividido em nove tópicos. A ferramenta `consultar_politicas` devolve só o trecho relevante. O prompt de sistema fica enxuto (persona + regras de ouro), e o modelo precisa *escolher* consultar o manual em vez de responder de memória. Com um manual tão curto, colocar tudo no prompt também funcionaria; escolhi a ferramenta pelo controle e pela clareza do trace (`--verbose`).

**Modelo: Claude Haiku 5.5 via API da Anthropic.** Tool use confiável, bom português, baixa latência e custo (importante para chat). Troca por outro modelo Claude com `EMPORIO_MODEL`. O prompt de sistema usa prompt caching.

**Persona e prompt.** Seguem o manual (seção 7.1): "informal mas profissional, como um amigo que entende de música". O prompt define quando usar cada ferramenta, regras de ouro (nunca inventar preço/estoque/prazo, promoção sempre com preço original, PIX não acumula com promoção) e o tratamento de fora de escopo e de tentativas de mudar as instruções.

**Privacidade (LGPD).** Pedido só é consultado com e-mail ou telefone do cadastro *e* o pedido precisa pertencer a esse cliente. A mensagem de erro é igual para "pedido não existe" e "pedido é de outra pessoa". A resposta nunca traz telefone, e-mail ou endereço, só o primeiro nome. Dois clientes têm o mesmo e-mail (Bruno Martins): com o número do pedido, o dono do pedido desempata; sem ele, o agente pede o telefone.

**Interface: CLI.** O foco é o agente. **Histórico:** em memória durante a conversa e em JSON por sessão (`--sessao`), para retomar um atendimento.

## Tratamento dos dados e suposições

- **Promoção só conta se `is_active=1`.** Se houver mais de uma ativa para o mesmo produto, vale a maior (o manual diz que não acumulam).
- **Disponível para compra = `status=active` e estoque > 0.** O Giannini GF-3D está "ativo" com estoque 0, e o Kala KA-ABP-CTG está "em breve" com estoque 2. Nenhum dos dois é vendável.
- **Filtro de preço usa o preço efetivo** (promocional, quando há promoção ativa).
- **Data de referência (`EMPORIO_HOJE`, padrão 2026-03-23).** Os CSVs são um retrato congelado (último pedido em 22/03/2026). Com o relógio real, todo prazo de devolução apareceria vencido. Os prazos são calculados contra essa data.
- **Data de recebimento.** Não existe nos dados. Uso `estimated_delivery` dos pedidos entregues como aproximação, e o agente avisa que é estimativa.
- **Prazo de defeito.** O manual diz 30 dias de troca (§4.2) e 90 dias de garantia legal (§8.1). A ferramenta devolve um `caminho` explícito: até 30 dias da compra, troca direto; de 31 a 90 dias do recebimento, garantia legal (registrar e encaminhar à equipe, sem prometer resultado); depois, garantia do fabricante.
- **Parcelamento.** A tabela do §3 diz "parcela mínima R$ 100" para crédito, mas §3.1 detalha faixas (até 3x sem mínimo, 4–6x R$ 80, 7–12x R$ 100). Segui o §3.1, que é mais específico.
- **Contatos duplicados no manual.** Telefone (67) 3341-4444 (cabeçalho e dados da empresa) × WhatsApp (67) 3321-4500 (§7), e e-mail com e sem acento. O agente usa (67) 3341-4444 e `contato@emporiodamusica.com.br`.
- **Catálogo.** O manual fala em "mais de 300 instrumentos" e inclui sopros, mas o CSV tem 65 produtos em 6 das 9 categorias (nenhum sopro, nenhuma corda orquestral). O agente só afirma o que está nos dados.
- **Inconsistências nos pedidos viram "alertas"** (`consultar_pedidos`), e o prompt manda o agente ser transparente, não prometer data e encaminhar à equipe. Casos achados na auditoria dos CSVs: pedido 8 "enviado" com previsão vencida há 23 dias; pedidos 9–12 confirmados há mais de 12 dias sem envio; pedidos pendentes há mais de 3 dias; pedido 14 com item "em breve"; pedidos 3 e 20 com total menor que a soma dos itens (o agente informa o total registrado e não inventa a causa).
- **Parcelas fora do manual em pedidos históricos** (pedidos 9, 16 e 18 têm parcela abaixo do mínimo da §3.1). Não corrigi os dados; `simular_pagamento` aplica as regras do manual para vendas novas.
- **Cancelamento antes do envio** não está no manual, então o agente encaminha à equipe em vez de prometer.

## Limitações conhecidas e próximos passos

- Não há verificação forte de identidade: e-mail/telefone são "algo que o cliente sabe", o que é fraco para um sistema real (um código por SMS/WhatsApp resolveria).
- Busca de produtos por substring normalizada. "Violão" ≠ "violões" no texto livre; o filtro de categoria cobre os casos comuns, mas busca semântica (embeddings) ajudaria com sinônimos ("cavaco", "guitarra de 7 cordas") e perguntas vagas ("algo pra começar").
- O horário da loja não conhece feriados; o `encaminhar_para_humano` só grava em arquivo, sem fila nem notificação.
- Sem avaliação automatizada de qualidade das respostas. Com mais tempo: um conjunto de conversas com critérios (LLM-as-judge) rodando no CI, para pegar regressões de prompt.
- O histórico enviado ao modelo é limitado às últimas ~40 mensagens (corte em turno de usuário); conversas muito longas perdem o começo.
- Sem streaming nem canal real (WhatsApp); a interface é CLI.
- O estado de um pedido é lido do CSV; na prática viria de uma API/banco.

## Uso de assistentes de código

Usei o **Claude Code** (Anthropic) como par de programação. Como foi usado:

- Pedi a ele um levantamento de armadilhas nos dados (e-mail duplicado, estoque 0 em produto "ativo", promoções inativas, inconsistências no manual). As suposições acima vêm dessa análise.
- A arquitetura (function calling, sem RAG, cálculos em código) foi definida na conversa com o Claude Code, que escreveu a primeira versão dos módulos, dos testes e deste README.
- As regras de negócio (prazos de devolução, parcelamento, verificação de pedido) têm testes automatizados em `tests/` e foram conferidas contra o texto do manual.
- Os commits do histórico foram feitos de forma incremental durante o desenvolvimento.

## Estrutura

```
emporio/            código (dados, ferramentas, prompt, agente, CLI)
data/               CSVs, PDF original e politicas.md (texto das políticas)
tests/              testes das ferramentas e do loop do agente (sem API)
exemplos/           conversas de exemplo geradas com o agente real
scripts/            gerar_exemplos.py
```
