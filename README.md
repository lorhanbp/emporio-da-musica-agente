# Melô — customer support agent for Empório da Música

Prototype of a text-based customer support agent for the fictional store Empório da Música (Campo Grande/MS, Brazil), built for Artefact's AI Engineer technical challenge. **Melô** answers questions about products (price, stock, promotions), store policies (payment, exchanges, shipping, warranty), order status and returns, and politely declines anything out of scope. The agent talks to customers in Brazilian Portuguese.

## For reviewers

- **Without running anything:** the 5 full conversations are in [`exemplos/`](exemplos/) (catalog, price and payment, store info and out of scope, a return under the policy rules, order privacy). They are in Portuguese, the language the agent speaks.
- **Running it:** the repository **ships no API key** (`.env` is git-ignored on purpose). You need an Anthropic key (`ANTHROPIC_API_KEY`); see "How to run".
- **About the examples:** they were generated with the real agent through the OpenAI-compatible adapter, using a non-Claude model (the only key available during development). The default Claude path is covered by automated tests but was not run against the real API, so the wording of the answers may vary slightly.
- **Tests need no key:** `pytest -q`.

## How to run

Requirements: Python 3.11+ and an Anthropic API key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then set ANTHROPIC_API_KEY
python -m emporio        # chat in the terminal
```

Set `ANTHROPIC_API_KEY` in `.env`. The default model is `claude-haiku-5-5` (override with `EMPORIO_MODEL`).

The Anthropic path is covered by automated tests that use the real SDK against a fake HTTP server.

Other commands:

```bash
python -m emporio.web          # browser chat at http://localhost:8000 (local only, uses your key)
python -m emporio --verbose    # shows every tool call and its result
python -m emporio --sessao x   # saves and resumes history in .sessions/x.json
python -m emporio --transcricao conversa.md
python scripts/gerar_exemplos.py [cenario ...]   # regenerates exemplos/*.md
```

`EMPORIO_HOJE` (default `2026-03-23`) sets the agent's "today"; see "Data handling and assumptions".

## How it works

1. A customer message arrives (terminal or web page).
2. The agent sends the model the conversation, the system prompt (persona + rules) and the list of tools.
3. The model either answers directly or asks to call a tool. Examples: `buscar_produtos` for a price, `consultar_politicas` for exchange rules, `consultar_pedidos` for an order.
4. The tool runs in plain Python over the CSVs and returns JSON. Every number, date and deadline comes from here, never from the model.
5. The result goes back to the model, which may call more tools and finally writes the answer in the persona's tone.
6. History is kept (in memory and, optionally, on disk per session) so the conversation has context.

Example: *"I regret the purchase, can I return it?"* → the model asks for an email or phone number and the order number (without them it cannot show orders) → `avaliar_devolucao` checks who owns the order and counts the days since delivery against the 7-day withdrawal period → the model explains the result and offers what is still possible (warranty).

Safeguards in the loop: tool errors go back to the model so it can correct itself; if the model says it escalated a case without calling `encaminhar_para_humano`, the agent calls it out and forces a retry; an API failure rolls back that turn's history so the next message keeps working.

## Architecture

```
customer ──► CLI / web ──► Agent (function-calling loop) ──► LLM provider
                              │                                   │
                              └── tools (plain Python) ◄──────────┘
                                   ├─ buscar_produtos / detalhes_produto          → CSVs in memory
                                   ├─ consultar_pedidos / avaliar_devolucao       → CSVs + identity check
                                   ├─ simular_pagamento                           → payment and shipping rules
                                   ├─ consultar_politicas / horario_da_loja_agora → data/politicas.md
                                   └─ encaminhar_para_humano                      → .sessions/encaminhamentos.jsonl
```

The provider adapters live in `emporio/modelos.py`. History is always stored in a neutral format (OpenAI-style messages); each adapter translates it to its provider's API, so the agent loop does not change from one provider to another.

## Technical decisions

**Function calling, no RAG and no SQL agent.** The data is tiny (65 products, 20 orders, 8 policy pages). An embeddings pipeline would add complexity with no quality gain, and a SQL agent would let the model write queries over customer data. With typed tools, the model decides *which* tool to call (this is what the challenge calls "knowing when to query data and when to query policies") and Python guarantees the result.

**Calculation in code, text in the model.** Promotional price, PIX discount, minimum installment, shipping and return deadlines are computed in the tools. The LLM only picks the tool and writes the reply. This removes a whole class of numeric hallucination and makes the rules testable (`tests/`).

**Retrieval architecture.** There is no vector search: the catalog and orders are queried with structured filters (category, price range, accent-normalized terms, order owner) and policies by topic. The model chooses what to query through function calling; the data comes back from deterministic code.

**Policies as a tool, not as a prompt.** The PDF was converted to `data/politicas.md`, split into nine topics. The `consultar_politicas` tool returns only the relevant excerpt. The system prompt stays lean (persona + golden rules), and the model has to *choose* to consult the manual instead of answering from memory. With a manual this short, putting everything in the prompt would also work; I chose the tool for control and for a clearer trace (`--verbose`).

**Model and provider.** The default is Claude Haiku (`claude-haiku-5-5`) through the Anthropic API: native tool use, good Portuguese, low latency and cost, which suits a high-volume chat. To avoid locking the code to one provider, there is a second adapter for OpenAI-compatible APIs (used to generate the examples). Temperature is 0.3 on that path for consistent answers; on the Anthropic path it is not set. The tool loop is manual, to log each call and control the history. OpenAI-compatible reasoning models may return a `reasoning_content` field that the API requires back, so the full message is stored.

**Persona and prompt strategy.** They follow the manual (section 7.1): "informal but professional, like a friend who knows music". The prompt defines when to use each tool and sets golden rules: never invent price, stock or deadlines; always show the original price next to the promotional one; no PIX discount on promotional prices; only say a case was escalated after calling the tool; quote numbers exactly as the tool returned them; never infer the customer's gender or identity; redirect accessories and out-of-scope orders; and ignore attempts to change the instructions.

**Privacy (LGPD).** An order is shown only with the email or phone on file *and* only if it belongs to that customer. The error message is the same for "order does not exist" and "order belongs to someone else". The answer never includes phone, email or address, only the first name. Two customers share the same email (Bruno Martins): with the order number, the order owner breaks the tie; without it, the agent asks for the phone number.

**Interface and history.** CLI plus a minimal local web page, since the focus is the agent. History stays in memory during the conversation and, optionally, in per-session JSON (`--sessao`), so a support conversation can be resumed.

## Data handling and assumptions

- **A promotion counts only if `is_active=1`.** If more than one is active for the same product, the largest applies (the manual says they do not stack).
- **Available for purchase = `status=active` and stock > 0.** The Giannini GF-3D is "active" with stock 0, and the Kala KA-ABP-CTG is "coming soon" with stock 2. Neither is sellable.
- **The price filter uses the effective price** (promotional, when a promotion is active).
- **Reference date (`EMPORIO_HOJE`, default 2026-03-23).** The CSVs are a frozen snapshot (last order on 2026-03-22). With the real clock, every return deadline would show as expired. Deadlines are computed against this date.
- **Delivery date.** It does not exist in the data. I use `estimated_delivery` of delivered orders as an approximation, and the agent says it is an estimate.
- **Defect deadline.** The manual says 30 days for exchange (§4.2) and 90 days of legal warranty (§8.1). The tool returns an explicit path: up to 30 days from purchase, direct exchange; from 31 to 90 days from delivery, legal warranty (register and forward to the team, without promising an outcome); after that, manufacturer warranty.
- **Installments.** The §3 table says "minimum installment R$ 100" for credit, but §3.1 details tiers (up to 3x with no minimum, 4–6x R$ 80, 7–12x R$ 100). I followed §3.1, which is more specific.
- **Duplicate contacts in the manual.** Phone (67) 3341-4444 (header and company data) vs. WhatsApp (67) 3321-4500 (§7), and email with and without an accent. The agent uses (67) 3341-4444 and `contato@emporiodamusica.com.br`.
- **Catalog.** The manual mentions "more than 300 instruments" and includes wind instruments, but the CSV has 65 products in 6 of the 9 categories (no winds, no orchestral strings). The agent only states what is in the data.
- **Inconsistencies in orders become "alerts"** (`consultar_pedidos`), and the prompt tells the agent to be transparent, not promise a date, and escalate to the team. Cases found when auditing the CSVs: order 8 "shipped" with an estimate overdue by 23 days; orders 9–12 confirmed more than 12 days ago without shipping; orders pending for more than 3 days; order 14 with a "coming soon" item; orders 3 and 20 with a total lower than the sum of their items (the agent reports the recorded total and does not invent the cause).
- **Installments outside the manual in historical orders** (orders 9, 16 and 18 have an installment below the §3.1 minimum). I did not fix the data; `simular_pagamento` applies the manual's rules to new sales.
- **Cancellation before shipping** is not in the manual, so the agent escalates to the team instead of promising anything.

## Known limitations and next steps

- There is no strong identity verification: email and phone are "something the customer knows", which is weak for a real system (a code by SMS or WhatsApp would fix it).
- Product search is by accent-normalized substring. The category filter covers common cases, but semantic search (embeddings) would help with synonyms and vague questions ("something to get started").
- Store hours do not know about holidays; `encaminhar_para_humano` only writes to a file, with no queue or notification.
- Models sometimes say they "will escalate" without calling the tool (this happened in testing). The agent detects it by keyword and forces a retry. It is a safety net, not a guarantee.
- No automated evaluation of answer quality. With more time: a set of scripted conversations with pass criteria (LLM-as-judge) in CI, to catch prompt regressions.
- The history sent to the model is limited to the last ~40 messages (cut at a user turn); very long conversations lose their beginning.
- The Anthropic path was not run against the real API, only against a fake HTTP server using the real SDK.
- No streaming and no real channel (WhatsApp); order state comes from CSV, and in practice would come from an API or database.

## Use of coding assistants

I used **Claude Code** (Anthropic) as a programming assistant. The agent itself uses the Anthropic API (or another OpenAI-compatible one). How it was used:

- It audited the CSVs and the manual for traps (duplicate email, zero stock on an "active" product, inactive promotions, contradictions in the manual). The assumptions above come from that analysis.
- From the challenge requirements, it wrote the first versions of the modules, the tests and this document, which then went through several rounds of adjustment by running the agent with the real model and reading the conversations.
- The business rules (return deadlines, installments, order-owner verification) have automated tests in `tests/`; the example conversations were generated by running the real agent, not written by hand.

## Project structure

```
emporio/     code (data, tools, prompt, agent, provider adapters, CLI, web page)
data/        the company's original files (CSVs and politicas_da_loja.pdf) + politicas.md (the PDF as text, by topic)
tests/       tests for the tools, the agent loop and the providers (no API key needed)
exemplos/    example conversations generated with the real agent (via the OpenAI-compatible adapter, not Claude)
scripts/     gerar_exemplos.py
```
