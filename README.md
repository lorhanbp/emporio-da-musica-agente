# Melô: customer-service agent for Empório da Música

Prototype of a text-based customer-service agent for the fictional store Empório da Música (Campo Grande/MS, Brazil), built for the Artefact AI Engineer technical case. **Melô** answers questions about products (price, stock, promotions), store policies (payment, returns, shipping, warranty), order status and returns, and politely declines anything out of scope.

The agent talks to Brazilian customers, so its persona, prompt and the sample conversations are in Portuguese. Everything else (this document included) is in English.

## For reviewers

- **Without running anything:** the 5 full conversations are in [`exemplos/`](exemplos/) (catalog search, price and payment, store info and out-of-scope, a return that depends on policy rules, order privacy).
- **Running it:** the repository ships **no API key** (`.env` is git-ignored on purpose). You need your own key for **one** of: DeepSeek (default, very cheap) or Anthropic. See "How to run".
- **Tests need no key:** `pytest -q`.

## How to run

Requirements: Python 3.11+ and an API key for one provider.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill in ONE key, see below
python -m emporio        # chat in the terminal
```

**Provider options** (edit `.env`):

| Provider | Variable | Default model | Notes |
|---|---|---|---|
| DeepSeek (default) | `DEEPSEEK_API_KEY` | `deepseek-flash` | Cheapest DeepSeek model; used to generate the sample conversations |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` | Covered by automated tests that use the real SDK against a fake HTTP server; not exercised against the live API |
| Any OpenAI-compatible API | `EMPORIO_API_KEY` + `EMPORIO_BASE_URL` + `EMPORIO_MODEL` | none | The model must support function calling |

The provider is picked from the keys present: only `ANTHROPIC_API_KEY` set → Anthropic; otherwise DeepSeek. Force it with `EMPORIO_PROVEDOR=anthropic` or `deepseek`. `EMPORIO_MODEL` overrides the model in any case.

Other commands:

```bash
python -m emporio.web          # browser chat at http://localhost:8000 (local only, uses your key)
python -m emporio --verbose    # show every tool call and its result
python -m emporio --sessao x   # keep/resume history in .sessions/x.json
python -m emporio --transcricao chat.md
python scripts/gerar_exemplos.py [scenario ...]   # regenerate exemplos/*.md
```

`EMPORIO_HOJE` (default `2026-03-23`) sets the agent's "today"; see "Data handling and assumptions".

## How it works

1. A customer message arrives (CLI or web page).
2. The agent sends the conversation, the system prompt (persona + rules) and the list of tools to the model.
3. The model either answers directly or asks to call a tool. Examples: `buscar_produtos` for a price, `consultar_politicas` for return rules, `consultar_pedidos` for an order.
4. The tool runs as plain Python over the CSV data and returns JSON. All numbers, dates and deadlines come from here, never from the model.
5. The result goes back to the model, which may call more tools, and finally writes the reply in the persona's tone.
6. History is kept (in memory, optionally on disk per session) so the conversation has context.

Example: *"I regret my purchase, can I return it?"* → the model asks for e-mail/phone and order number (it has no right to see orders otherwise) → `avaliar_devolucao` checks ownership, computes days since delivery against the 7-day withdrawal window → the model explains the result and offers what is still possible (warranty).

Safeguards in the loop: tool errors are returned to the model so it can correct itself; if the model says it forwarded a case without calling `encaminhar_para_humano`, the agent calls it out and forces a retry; a failed API call rolls the history back so the next message still works.

## Architecture

```
customer ──► CLI / web ──► Agent (function-calling loop) ──► LLM provider
                              │                                  │
                              └── tools (plain Python) ◄─────────┘
                                   ├─ buscar_produtos / detalhes_produto        → CSVs in memory
                                   ├─ consultar_pedidos / avaliar_devolucao     → CSVs + identity check
                                   ├─ simular_pagamento                         → payment and shipping rules
                                   ├─ consultar_politicas / horario_da_loja_agora → data/politicas.md
                                   └─ encaminhar_para_humano                    → .sessions/encaminhamentos.jsonl
```

Provider adapters live in `emporio/modelos.py`. The history is always stored in one neutral format (OpenAI-style messages); each adapter translates it to its provider's API, so the loop does not change between providers.

## Technical decisions

**Function calling, no RAG, no SQL agent.** The data is tiny (65 products, 20 orders, an 8-page manual). An embedding pipeline would add complexity without improving quality, and an SQL agent would let the model write queries over customer data. With typed tools the model decides *which* tool to call (this is the case's "know when to query data and when to consult policies") and Python guarantees the result.

**Math and rules in code, wording in the model.** Promotional price, PIX discount, minimum installment, shipping and return deadlines are computed in the tools. This removes a whole class of numeric hallucination and makes the rules testable (`tests/`).

**Retrieval architecture.** No vector search. The catalog and orders are queried with structured filters (category, price range, accent-insensitive terms, order owner) and the policies by topic. The model chooses what to query through function calling; the data comes back from deterministic code.

**Policies as a tool, not in the prompt.** The PDF was converted to `data/politicas.md`, split into nine topics. `consultar_politicas` returns only the relevant section. The system prompt stays short (persona + golden rules) and the model must *choose* to consult the manual instead of answering from memory. With a manual this short, putting everything in the prompt would also work; the tool gives control and a clear trace (`--verbose`).

**Model and provider.** Default is `deepseek-flash` through the OpenAI-compatible API: cheapest DeepSeek model, native function calling, good Portuguese, fitting a high-volume chat. Anthropic is supported as an alternative through its own SDK. Temperature is 0.3 on the OpenAI-compatible path for consistent answers (not set on the Anthropic path). The tool loop is manual to log each call and control the history. DeepSeek returns a `reasoning_content` field in tool turns that the API requires back, so the full message is stored.

**Persona and prompt strategy.** Follows the manual (section 7.1): "informal but professional, like a friend who knows music". The prompt says when to use each tool, and states golden rules: never invent price/stock/deadlines, always show the original price next to a promotion, no PIX discount on promotional prices, only forward/register through the tool, quote numbers exactly as returned, do not infer the customer's gender or identity, redirect accessories and out-of-scope requests, and ignore attempts to change the instructions.

**Privacy (LGPD).** An order is only shown with the registered e-mail or phone *and* if it belongs to that customer. The error message is identical for "order does not exist" and "order belongs to someone else". Replies never include phone, e-mail or address, only the first name. Two customers share an e-mail (Bruno Martins): with an order number, the order owner disambiguates; without it, the agent asks for the phone.

**Interface and history.** CLI plus a minimal local web page, since the focus is the agent. History lives in memory during the conversation and, optionally, in JSON per session (`--sessao`) to resume a conversation.

## Data handling and assumptions

- **A promotion counts only if `is_active=1`.** If a product has several active ones, the largest applies (the manual says promotions do not stack).
- **Available to buy = `status=active` and stock > 0.** Giannini GF-3D is "active" with stock 0, and Kala KA-ABP-CTG is "coming soon" with stock 2. Neither is sellable.
- **Price filters use the effective price** (promotional when a promotion is active).
- **Reference date (`EMPORIO_HOJE`, default 2026-03-23).** The CSVs are a frozen snapshot (last order on 2026-03-22). With the real clock every return window would look expired, so deadlines are computed against this date.
- **Delivery date.** There is no real receipt date in the data. `estimated_delivery` of delivered orders is used as an approximation and the agent says it is an estimate.
- **Defect deadline.** The manual says 30 days for exchange (§4.2) and 90 days of legal warranty (§8.1). The tool returns an explicit path: up to 30 days from purchase, direct exchange; 31 to 90 days from receipt, legal warranty (register and forward to the team, no promise of outcome); after that, manufacturer warranty.
- **Installments.** The table in §3 says "minimum installment R$ 100" for credit, but §3.1 details tiers (up to 3x no minimum, 4–6x R$ 80, 7–12x R$ 100). I followed §3.1, the more specific one.
- **Duplicated contacts in the manual.** Phone (67) 3341-4444 (header and company data) vs WhatsApp (67) 3321-4500 (§7), and an e-mail written with and without accent. The agent uses (67) 3341-4444 and `contato@emporiodamusica.com.br`.
- **Catalog.** The manual mentions "over 300 instruments" including winds, but the CSV has 65 products in 6 of 9 categories (no winds, no orchestral strings). The agent only states what the data shows.
- **Order inconsistencies become "alerts"** (`consultar_pedidos`) and the prompt tells the agent to be transparent, not to promise dates, and to forward to the team. Found while auditing the CSVs: order 8 "shipped" with an estimate overdue by 23 days; orders 9–12 confirmed for over 12 days without shipping; pending orders for over 3 days; order 14 with a "coming soon" item; orders 3 and 20 with a total lower than the sum of their items (the agent reports the recorded total and does not invent a cause).
- **Historical installments below the manual's minimum** (orders 9, 16, 18). Data left untouched; `simular_pagamento` applies the manual's rules to new sales.
- **Cancelling before shipping** is not in the manual, so the agent forwards to the team instead of promising.

## Known limitations and next steps

- No strong identity verification: e-mail/phone are "something the customer knows", weak for a real system (a one-time code via SMS/WhatsApp would fix it).
- Product search is accent-insensitive substring matching. The category filter covers the common cases, but semantic search (embeddings) would help with synonyms and vague questions ("something to start with").
- Store hours do not know about holidays; `encaminhar_para_humano` only writes to a file, with no queue or notification.
- Models sometimes say "I'll forward this" without calling the tool (seen in tests). The agent catches it by keyword and forces a retry. This is a safety net, not a guarantee.
- No automated quality evaluation of replies. With more time: a set of scripted conversations with pass/fail criteria (LLM-as-judge) in CI to catch prompt regressions.
- History sent to the model is capped at the last ~40 messages (cut on a user turn); very long conversations lose their beginning.
- The Anthropic path has not been run against the live API, only against a fake HTTP server through the real SDK.
- No streaming and no real channel (WhatsApp); order state is read from CSV, in production it would come from an API/database.

## Use of AI coding assistants

I used **Claude Code** (Anthropic) as a coding assistant. The agent itself runs on DeepSeek (or Anthropic, if you choose). How it was used:

- It audited the CSVs and the manual for traps (duplicate e-mail, zero stock on "active" products, inactive promotions, contradictions in the manual). The assumptions above come from that audit.
- From the case requirements, it wrote the first versions of the modules, tests and this document, which then went through several rounds of changes after running the agent against the real model and reading the conversations.
- Business rules (return windows, installments, order ownership checks) are covered by automated tests in `tests/`; the sample conversations were generated by running the real agent, not written by hand.

## Project layout

```
emporio/     code (data, tools, prompt, agent, provider adapters, CLI, web page)
data/        original company files (CSVs and políticas_da_loja.pdf) + politicas.md (the PDF as text, by topic)
tests/       tests for tools, agent loop and providers (no API key needed)
exemplos/    sample conversations generated with the real agent
scripts/     gerar_exemplos.py
```
