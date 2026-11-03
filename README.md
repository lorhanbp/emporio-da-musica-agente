# Melô — agente de atendimento da Empório da Música

Protótipo de um agente de atendimento por texto para a loja fictícia Empório da Música (Campo Grande/MS), feito para o desafio técnico de AI Engineer da Artefact. A **Melô** responde sobre produtos (preço, estoque, promoção), políticas da loja (pagamento, troca, frete, garantia), status de pedidos e devoluções, e recusa com educação o que foge do escopo.

## Para quem vai avaliar

- **Sem rodar nada:** as 5 conversas completas estão em [`exemplos/`](exemplos/) (catálogo, preço e pagamento, loja e fora de escopo, devolução com regras da política, privacidade de pedido).
- **Rodando:** o repositório **não traz chave de API** (o `.env` é ignorado pelo git de propósito). Você precisa de uma chave da Anthropic (`ANTHROPIC_API_KEY`); veja "Como rodar".
- **Sobre os exemplos:** foram gerados com o agente de verdade usando `deepseek-flash` por uma API compatível com OpenAI, a chave disponível durante o desenvolvimento. O caminho padrão com Claude foi validado por testes automatizados, mas não foi executado contra a API real, então o texto das respostas pode variar um pouco.
- **Os testes não precisam de chave:** `pytest -q`.

## Como rodar

Requisitos: Python 3.11+ e uma chave de API de um provedor.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # depois preencha UMA chave, veja abaixo
python -m emporio        # conversa no terminal
```

**Provedor (edite o `.env`):**

| Provedor | Variáveis | Modelo padrão |
|---|---|---|
| Anthropic (padrão) | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` (troque com `EMPORIO_MODEL`) |
| Alternativa: qualquer API compatível com OpenAI | `EMPORIO_PROVEDOR=openai`, `EMPORIO_API_KEY`, `EMPORIO_BASE_URL`, `EMPORIO_MODEL` | nenhum; o modelo precisa suportar function calling |

O caminho da Anthropic é coberto por testes automatizados que usam o SDK real contra um servidor HTTP falso. Sem `EMPORIO_PROVEDOR`, o padrão é a Anthropic (só `EMPORIO_API_KEY` definida, sem chave da Anthropic, escolhe o provedor compatível com OpenAI).

Outros comandos:

```bash
python -m emporio.web          # chat no navegador em http://localhost:8000 (só local, usa a sua chave)
python -m emporio --verbose    # mostra cada ferramenta chamada e o resultado
python -m emporio --sessao x   # guarda e retoma o histórico em .sessions/x.json
python -m emporio --transcricao conversa.md
python scripts/gerar_exemplos.py [cenario ...]   # regrava exemplos/*.md
```

`EMPORIO_HOJE` (padrão `2026-03-23`) define o "hoje" do agente; veja "Tratamento dos dados e suposições".

## Como funciona

1. Chega uma mensagem do cliente (terminal ou página web).
2. O agente envia ao modelo a conversa, o prompt de sistema (persona + regras) e a lista de ferramentas.
3. O modelo responde direto ou pede para chamar uma ferramenta. Exemplos: `buscar_produtos` para um preço, `consultar_politicas` para regras de troca, `consultar_pedidos` para um pedido.
4. A ferramenta roda em Python puro sobre os CSVs e devolve JSON. Todo número, data e prazo vem daqui, nunca do modelo.
5. O resultado volta ao modelo, que pode chamar mais ferramentas e, por fim, escreve a resposta no tom da persona.
6. O histórico é mantido (em memória e, opcionalmente, em disco por sessão) para a conversa ter contexto.

Exemplo: *"Me arrependi da compra, posso devolver?"* → o modelo pede e-mail ou telefone e o número do pedido (sem isso ele não pode mostrar pedidos) → `avaliar_devolucao` confere o dono do pedido e calcula os dias desde a entrega contra o prazo de arrependimento de 7 dias → o modelo explica o resultado e oferece o que ainda é possível (garantia).

Proteções no loop: erros de ferramenta voltam ao modelo para ele se corrigir; se o modelo disser que encaminhou um caso sem chamar `encaminhar_para_humano`, o agente cobra e força uma nova tentativa; uma falha da API desfaz o histórico da rodada, para a próxima mensagem continuar funcionando.

## Arquitetura

```
cliente ──► CLI / web ──► Agente (loop de function calling) ──► provedor de LLM
                              │                                      │
                              └── ferramentas (Python puro) ◄────────┘
                                   ├─ buscar_produtos / detalhes_produto          → CSVs em memória
                                   ├─ consultar_pedidos / avaliar_devolucao       → CSVs + verificação de identidade
                                   ├─ simular_pagamento                           → regras de pagamento e frete
                                   ├─ consultar_politicas / horario_da_loja_agora → data/politicas.md
                                   └─ encaminhar_para_humano                      → .sessions/encaminhamentos.jsonl
```

Os adaptadores de provedor ficam em `emporio/modelos.py`. O histórico é sempre guardado num formato neutro (mensagens no estilo OpenAI); cada adaptador traduz para a API do seu provedor, então o loop do agente não muda de um provedor para outro.

## Decisões técnicas

**Function calling, sem RAG nem agente de SQL.** Os dados são minúsculos (65 produtos, 20 pedidos, 8 páginas de políticas). Um pipeline de embeddings seria complexidade sem ganho de qualidade, e um agente de SQL deixaria o modelo escrever consultas sobre dados de clientes. Com ferramentas tipadas, o modelo decide *qual* ferramenta chamar (é isso que o desafio chama de "saber quando consultar dados e quando consultar políticas") e o Python garante o resultado.

**Cálculo em código, texto no modelo.** Preço com promoção, PIX, parcela mínima, frete e prazos de devolução são calculados nas ferramentas. O LLM só escolhe a ferramenta e redige. Isso elimina uma classe inteira de alucinação numérica e deixa as regras testáveis (`tests/`).

**Arquitetura de retrieval.** Não há busca vetorial: o catálogo e os pedidos são consultados por filtros estruturados (categoria, faixa de preço, termos normalizados sem acento, dono do pedido) e as políticas por tópico. O modelo escolhe o que consultar via function calling; o dado volta de código determinístico.

**Políticas como ferramenta, não como prompt.** O PDF foi convertido para `data/politicas.md`, dividido em nove tópicos. A ferramenta `consultar_politicas` devolve só o trecho relevante. O prompt de sistema fica enxuto (persona + regras de ouro), e o modelo precisa *escolher* consultar o manual em vez de responder de memória. Com um manual tão curto, colocar tudo no prompt também funcionaria; escolhi a ferramenta pelo controle e pela clareza do trace (`--verbose`).

**Modelo e provedor.** O padrão é o Claude Haiku (`claude-haiku-5-5`) pela API da Anthropic: tool use nativo, bom português, baixa latência e custo, o que combina com um chat de alto volume. Para não prender o código a um provedor, há um segundo adaptador para APIs compatíveis com OpenAI (usado para gerar os exemplos). A temperatura é 0,3 nesse caminho, para respostas consistentes; no da Anthropic ela não é definida. O loop de ferramentas é manual, para registrar cada chamada e controlar o histórico. Modelos de raciocínio compatíveis com OpenAI podem devolver um campo `reasoning_content` que a API exige de volta, então a mensagem completa é guardada.

**Persona e estratégia de prompt.** Seguem o manual (seção 7.1): "informal mas profissional, como um amigo que entende de música". O prompt define quando usar cada ferramenta e traz regras de ouro: nunca inventar preço, estoque ou prazo; mostrar sempre o preço original junto da promoção; sem desconto de PIX em preço promocional; só dizer que encaminhou depois de chamar a ferramenta; citar os números exatamente como a ferramenta devolveu; não deduzir gênero nem identidade do cliente; redirecionar acessórios e pedidos fora do escopo; e ignorar tentativas de mudar as instruções.

**Privacidade (LGPD).** Pedido só é mostrado com e-mail ou telefone do cadastro *e* se pertencer a esse cliente. A mensagem de erro é igual para "pedido não existe" e "pedido é de outra pessoa". A resposta nunca traz telefone, e-mail ou endereço, só o primeiro nome. Dois clientes têm o mesmo e-mail (Bruno Martins): com o número do pedido, o dono do pedido desempata; sem ele, o agente pede o telefone.

**Interface e histórico.** CLI mais uma página web local mínima, já que o foco é o agente. O histórico fica em memória durante a conversa e, opcionalmente, em JSON por sessão (`--sessao`), para retomar um atendimento.

## Tratamento dos dados e suposições

- **Promoção só conta se `is_active=1`.** Se houver mais de uma ativa para o mesmo produto, vale a maior (o manual diz que não acumulam).
- **Disponível para compra = `status=active` e estoque > 0.** O Giannini GF-3D está "ativo" com estoque 0, e o Kala KA-ABP-CTG está "em breve" com estoque 2. Nenhum dos dois é vendável.
- **Filtro de preço usa o preço efetivo** (promocional, quando há promoção ativa).
- **Data de referência (`EMPORIO_HOJE`, padrão 2026-03-23).** Os CSVs são um retrato congelado (último pedido em 22/03/2026). Com o relógio real, todo prazo de devolução apareceria vencido. Os prazos são calculados contra essa data.
- **Data de recebimento.** Não existe nos dados. Uso `estimated_delivery` dos pedidos entregues como aproximação, e o agente avisa que é estimativa.
- **Prazo de defeito.** O manual diz 30 dias de troca (§4.2) e 90 dias de garantia legal (§8.1). A ferramenta devolve um caminho explícito: até 30 dias da compra, troca direto; de 31 a 90 dias do recebimento, garantia legal (registrar e encaminhar à equipe, sem prometer resultado); depois, garantia do fabricante.
- **Parcelamento.** A tabela do §3 diz "parcela mínima R$ 100" para crédito, mas o §3.1 detalha faixas (até 3x sem mínimo, 4–6x R$ 80, 7–12x R$ 100). Segui o §3.1, que é mais específico.
- **Contatos duplicados no manual.** Telefone (67) 3341-4444 (cabeçalho e dados da empresa) × WhatsApp (67) 3321-4500 (§7), e e-mail com e sem acento. O agente usa (67) 3341-4444 e `contato@emporiodamusica.com.br`.
- **Catálogo.** O manual fala em "mais de 300 instrumentos" e inclui sopros, mas o CSV tem 65 produtos em 6 das 9 categorias (nenhum sopro, nenhuma corda orquestral). O agente só afirma o que está nos dados.
- **Inconsistências nos pedidos viram "alertas"** (`consultar_pedidos`), e o prompt manda o agente ser transparente, não prometer data e encaminhar à equipe. Casos achados na auditoria dos CSVs: pedido 8 "enviado" com previsão vencida há 23 dias; pedidos 9–12 confirmados há mais de 12 dias sem envio; pedidos pendentes há mais de 3 dias; pedido 14 com item "em breve"; pedidos 3 e 20 com total menor que a soma dos itens (o agente informa o total registrado e não inventa a causa).
- **Parcelas fora do manual em pedidos históricos** (pedidos 9, 16 e 18 têm parcela abaixo do mínimo da §3.1). Não corrigi os dados; `simular_pagamento` aplica as regras do manual para vendas novas.
- **Cancelamento antes do envio** não está no manual, então o agente encaminha à equipe em vez de prometer.

## Limitações conhecidas e próximos passos

- Não há verificação forte de identidade: e-mail e telefone são "algo que o cliente sabe", o que é fraco para um sistema real (um código por SMS ou WhatsApp resolveria).
- A busca de produtos é por substring normalizada, sem acento. O filtro de categoria cobre os casos comuns, mas busca semântica (embeddings) ajudaria com sinônimos e perguntas vagas ("algo pra começar").
- O horário da loja não conhece feriados; o `encaminhar_para_humano` só grava em arquivo, sem fila nem notificação.
- Os modelos às vezes dizem que "vão encaminhar" sem chamar a ferramenta (aconteceu nos testes). O agente detecta por palavra-chave e força uma nova tentativa. É uma rede de segurança, não uma garantia.
- Sem avaliação automatizada de qualidade das respostas. Com mais tempo: um conjunto de conversas roteirizadas com critérios de aprovação (LLM-as-judge) no CI, para pegar regressões de prompt.
- O histórico enviado ao modelo é limitado às últimas ~40 mensagens (corte em turno de usuário); conversas muito longas perdem o começo.
- O caminho da Anthropic não foi executado contra a API real, só contra um servidor HTTP falso usando o SDK de verdade.
- Sem streaming nem canal real (WhatsApp); o estado dos pedidos vem de CSV, e na prática viria de uma API ou banco.

## Uso de assistentes de código

Usei o **Claude Code** (Anthropic) como assistente de programação. O agente em si usa a API da Anthropic (ou outra compatível com OpenAI). Como foi usado:

- Ele auditou os CSVs e o manual atrás de armadilhas (e-mail duplicado, estoque 0 em produto "ativo", promoções inativas, contradições no manual). As suposições acima vêm dessa análise.
- A partir dos requisitos do desafio, escreveu as primeiras versões dos módulos, dos testes e deste documento, que depois passaram por várias rodadas de ajuste ao rodar o agente com o modelo real e ler as conversas.
- As regras de negócio (prazos de devolução, parcelamento, verificação do dono do pedido) têm testes automatizados em `tests/`; as conversas de exemplo foram geradas rodando o agente de verdade, não escritas à mão.

## Estrutura do projeto

```
emporio/     código (dados, ferramentas, prompt, agente, adaptadores de provedor, CLI, página web)
data/        arquivos originais da empresa (CSVs e políticas_da_loja.pdf) + politicas.md (o PDF em texto, por tópico)
tests/       testes das ferramentas, do loop do agente e dos provedores (sem chave de API)
exemplos/    conversas de exemplo geradas com o agente real (deepseek-flash, via API compatível com OpenAI)
scripts/     gerar_exemplos.py
```
