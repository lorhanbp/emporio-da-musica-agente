"""Ferramentas (function calling) do agente.

Regra de ouro: tudo que é número, data, estoque ou regra com prazo é calculado aqui em Python,
nunca pelo LLM. O modelo só decide *qual* ferramenta chamar e redige a resposta.
"""
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config
from .dados import STATUS_PEDIDO, STATUS_PRODUTO, carregar, normalizar, so_digitos

_STOPWORDS = {"de", "da", "do", "com", "para", "um", "uma", "o", "a", "e", "que", "tem", "ate", "no", "na"}
_TOPICOS = ["sobre", "horario", "pagamento", "trocas", "frete", "promocoes", "atendimento", "garantia", "privacidade"]


def _politicas() -> dict[str, str]:
    texto = (config.DADOS / "politicas.md").read_text(encoding="utf-8")
    secoes = re.split(r"^## (\w+)\n", texto, flags=re.M)
    return {chave: corpo.strip() for chave, corpo in zip(secoes[1::2], secoes[2::2])}


# ---------------------------------------------------------------- produtos

def _resumo_produto(p: dict) -> dict:
    promo = p["promocao"]
    return {
        "produto_id": p["id"],
        "nome": p["nome"],
        "categoria": p["categoria"],
        "preco_tabela": p["preco_tabela"],
        "promocao_ativa": promo,
        "disponivel_para_compra": p["disponivel"],
        "unidades_em_estoque": p["estoque"] if p["disponivel"] else 0,
        "situacao_no_catalogo": STATUS_PRODUTO[p["status"]],
        "especificacoes": "; ".join(f"{k}: {v}" for k, v in p["specs"].items()),
    }


def _preco_efetivo(p: dict) -> float:
    return p["promocao"]["preco_promocional"] if p["promocao"] else p["preco_tabela"]


def buscar_produtos(
    consulta: str = "",
    categoria: str = "",
    preco_min: float | None = None,
    preco_max: float | None = None,
    incluir_indisponiveis: bool = False,
    limite: int = 8,
) -> dict:
    db = carregar()
    tokens = [t for t in normalizar(consulta).split() if t not in _STOPWORDS]
    cat = normalizar(categoria)
    achados = []
    for p in db["produtos"].values():
        if cat and cat not in normalizar(p["categoria"]):
            continue
        texto = normalizar(" ".join([p["nome"], p["categoria"], p["descricao"], *map(str, p["specs"].values())]))
        if not all(t in texto for t in tokens):
            continue
        preco = _preco_efetivo(p)
        if (preco_min is not None and preco < preco_min) or (preco_max is not None and preco > preco_max):
            continue
        if not incluir_indisponiveis and not p["disponivel"]:
            continue
        achados.append(p)
    achados.sort(key=lambda p: (not p["disponivel"], _preco_efetivo(p)))
    limite = max(1, min(limite, 15))
    return {
        "total_encontrado": len(achados),
        "mostrando": min(limite, len(achados)),
        "produtos": [_resumo_produto(p) for p in achados[:limite]],
        "nota": "Filtro de preço considera o preço promocional quando há promoção ativa. "
        "Se veio vazio, tente menos termos ou incluir_indisponiveis=true.",
    }


def detalhes_produto(produto_id: int) -> dict:
    p = carregar()["produtos"].get(int(produto_id))
    if not p:
        return {"erro": f"produto {produto_id} não existe no catálogo"}
    return {**_resumo_produto(p), "descricao": p["descricao"]}


# ---------------------------------------------------------------- políticas e loja

def consultar_politicas(topico: str) -> dict:
    pol = _politicas()
    if topico not in pol:
        return {"erro": f"tópico inválido. Use um de: {', '.join(pol)}"}
    return {"topico": topico, "texto": pol[topico]}


def horario_da_loja_agora(agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(ZoneInfo(config.FUSO))
    dia, hora = agora.weekday(), agora.hour + agora.minute / 60
    if dia <= 4:
        abre, fecha = 9, 18
    elif dia == 5:
        abre, fecha = 9, 13
    else:
        abre = fecha = None
    aberta = abre is not None and abre <= hora < fecha
    return {
        "agora": agora.strftime("%A, %d/%m/%Y %H:%M"),
        "loja_aberta": aberta,
        "aviso": "Feriados: loja fechada (esta ferramenta não conhece feriados).",
    }


def simular_pagamento(valor: float, em_promocao: bool = False) -> dict:
    """Aplica as regras de pagamento e frete do manual (seções 3 e 5)."""
    if valor <= 0:
        return {"erro": "valor deve ser positivo"}
    pix = round(valor, 2) if em_promocao else round(valor * 0.95, 2)
    parcelas = []
    for n in range(1, 13):
        valor_parcela = valor / n
        minimo = 50 if n <= 3 else 80 if n <= 6 else 100
        if n == 1 or valor_parcela >= minimo:
            parcelas.append({"parcelas": n, "valor_parcela": round(valor_parcela, 2)})
    return {
        "valor_base": round(valor, 2),
        "pix_a_vista": pix,
        "pix_desconto_5pct_aplicado": not em_promocao,
        "debito_ou_boleto_a_vista": round(valor, 2),
        "credito_sem_juros": parcelas,
        "frete_campo_grande_e_regiao": 0.0 if valor > 500 else 35.0,
        "frete_outras_cidades": "calculado pelo CEP no fechamento do pedido",
    }


# ---------------------------------------------------------------- pedidos (com verificação)

def _clientes_do_contato(contato: str) -> list[dict]:
    db = carregar()["clientes"].values()
    contato = (contato or "").strip().lower()
    if "@" in contato:
        return [c for c in db if c["email"] == contato]
    d = so_digitos(contato)
    d = d[2:] if d.startswith("55") and len(d) > 11 else d
    return [c for c in db if len(d) >= 10 and c["telefone"].endswith(d[-10:])] if d else []


def _verificar(contato: str, pedido_id: int | None) -> tuple[dict | None, dict | None]:
    """(cliente, erro). Mensagem de erro é genérica de propósito: não revela se o pedido existe."""
    clientes = _clientes_do_contato(contato)
    pedido = carregar()["pedidos"].get(int(pedido_id)) if pedido_id is not None else None
    if len(clientes) > 1 and pedido:  # e-mail repetido no cadastro: o dono do pedido desempata
        clientes = [c for c in clientes if c["id"] == pedido["cliente_id"]]
    if len(clientes) > 1:
        return None, {"erro": "contato ambíguo: peça o telefone com DDD para identificar o cadastro"}
    if not clientes:
        return None, {"erro": "não encontrei cadastro com esse contato. Peça o e-mail ou telefone usado na compra"}
    if pedido_id is not None and (not pedido or pedido["cliente_id"] != clientes[0]["id"]):
        return None, {"erro": f"não encontrei o pedido {pedido_id} para esse cadastro"}
    return clientes[0], None


def _pagamento(codigo: str) -> str:
    if codigo.startswith("credit_"):
        return f"cartão de crédito em {codigo.split('_')[1]}"
    return {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto"}.get(codigo, codigo)


def _alertas(p: dict) -> list[str]:
    """Inconsistências do pedido que o agente NÃO deve esconder nem 'resolver' inventando."""
    db = carregar()["produtos"]
    dias = (config.HOJE - date.fromisoformat(p["data"])).days
    avisos = []
    if p["status"] == "shipped" and p["previsao_entrega"]:
        atraso = (config.HOJE - date.fromisoformat(p["previsao_entrega"])).days
        if atraso > 0:
            avisos.append(f"previsão de entrega venceu há {atraso} dias e o pedido segue como enviado: não prometa "
                          "nova data, peça desculpas e encaminhe à equipe para checar com a transportadora")
    if p["status"] == "pending" and dias > 3:
        avisos.append(f"pagamento sem confirmação há {dias} dias (acima do normal): oriente e encaminhe à equipe")
    if p["status"] == "confirmed" and dias > 12:
        avisos.append(f"pedido confirmado há {dias} dias e ainda não enviado (acima do prazo normal): peça desculpas "
                      "e encaminhe à equipe; não prometa data")
    if p["status"] in ("pending", "confirmed"):
        nao_vendaveis = [db[i["produto_id"]]["nome"] for i in p["itens"] if db[i["produto_id"]]["status"] != "active"]
        if nao_vendaveis:
            avisos.append(f"contém item fora de linha ou 'em breve' ({', '.join(nao_vendaveis)}): não prometa prazo, "
                          "encaminhe à equipe")
    soma = sum(db[i["produto_id"]]["preco_tabela"] * i["quantidade"] for i in p["itens"])
    if abs(soma - p["total"]) > 0.5:
        avisos.append(f"total registrado (R$ {p['total']:.2f}) difere da soma dos itens a preço de tabela atual "
                      f"(R$ {soma:.2f}); não explique a diferença, informe o total registrado")
    return avisos


def _pedido_publico(pedido: dict) -> dict:
    db = carregar()
    return {
        "pedido_id": pedido["id"],
        "data_do_pedido": pedido["data"],
        "status": STATUS_PEDIDO[pedido["status"]],
        "total": pedido["total"],
        "forma_de_pagamento": _pagamento(pedido["pagamento"]),
        "codigo_de_rastreio": pedido["rastreio"],
        "previsao_de_entrega": pedido["previsao_entrega"],
        "observacao": pedido["observacao"],
        "itens": [
            {"produto": db["produtos"][i["produto_id"]]["nome"], "quantidade": i["quantidade"]}
            for i in pedido["itens"]
        ],
        "alertas": _alertas(pedido),
    }


def consultar_pedidos(contato: str, pedido_id: int | None = None) -> dict:
    cliente, erro = _verificar(contato, pedido_id)
    if erro:
        return erro
    db = carregar()["pedidos"]
    if pedido_id is not None:
        pedidos = [db[int(pedido_id)]]
    else:
        pedidos = sorted((p for p in db.values() if p["cliente_id"] == cliente["id"]), key=lambda p: p["data"])
    return {
        "cliente": cliente["nome"].split()[0],
        "pedidos": [_pedido_publico(p) for p in pedidos],
        "nota": "Previsão de entrega é estimativa; só existe rastreio depois do envio.",
    }


def avaliar_devolucao(contato: str, pedido_id: int, motivo: str) -> dict:
    """Calcula os prazos de troca/devolução do manual (seção 4 e 8) para um pedido."""
    cliente, erro = _verificar(contato, pedido_id)
    if erro:
        return erro
    p = carregar()["pedidos"][int(pedido_id)]
    saida = {"pedido": _pedido_publico(p), "motivo": motivo, "hoje": config.HOJE.isoformat()}

    if p["status"] == "cancelled":
        return {**saida, "situacao": "pedido já cancelado: não há o que devolver", "observacao": p["observacao"]}
    if p["status"] in ("pending", "confirmed"):
        return {
            **saida,
            "situacao": "pedido ainda não foi enviado, então não há devolução; o cliente quer cancelar. "
            "O manual não detalha o cancelamento antes do envio: encaminhar à equipe (encaminhar_para_humano).",
        }
    if p["status"] == "shipped":
        return {
            **saida,
            "situacao": "pedido em trânsito, ainda não recebido. Os 7 dias do arrependimento contam a partir do "
            "recebimento. Em caso de avaria na entrega, recusar o recebimento e avisar a loja.",
        }

    # delivered. Não há data real de recebimento nos dados: usa-se a previsão de entrega como aproximação.
    recebido = date.fromisoformat(p["previsao_entrega"])
    comprado = date.fromisoformat(p["data"])
    dias_receb = (config.HOJE - recebido).days
    dias_compra = (config.HOJE - comprado).days
    regras = {
        "arrependimento": {"prazo_dias": 7, "contado_desde": "recebimento", "decorridos": dias_receb,
                           "dentro_do_prazo": dias_receb <= 7},
        "preferencia": {"prazo_dias": 7, "contado_desde": "recebimento", "decorridos": dias_receb,
                        "dentro_do_prazo": dias_receb <= 7},
        "defeito": {"prazo_troca_dias": 30, "contado_desde": "data da compra", "decorridos": dias_compra,
                    "dentro_do_prazo": dias_compra <= 30,
                    "garantia_legal_90_dias_dentro": dias_receb <= 90},
    }
    if motivo not in regras:
        return {"erro": "motivo deve ser: arrependimento, preferencia ou defeito"}
    nomes = " ".join(normalizar(i["produto"]) for i in saida["pedido"]["itens"])
    if motivo == "defeito":
        if dias_compra <= 30:
            caminho = "troca direto com a loja (até 30 dias da compra)"
        elif dias_receb <= 90:
            caminho = ("passou dos 30 dias de troca, mas está na garantia legal de 90 dias contra defeito de "
                       "fabricação: registrar e encaminhar à equipe/gerência, sem prometer o resultado")
        else:
            caminho = "fora da garantia legal; orientar a acionar a garantia do fabricante (a loja intermedeia a pedido)"
        regras["defeito"]["caminho"] = caminho
    return {
        **saida,
        "situacao": "pedido entregue",
        "regra_aplicavel": regras[motivo],
        "recebimento_considerado": f"{recebido.isoformat()} (estimado: os dados só têm a previsão de entrega)",
        "condicoes": "embalagem original, sem uso, com acessórios e manuais. "
        "Arrependimento: reembolso na forma original em até 10 dias úteis, frete de devolução por conta da loja.",
        "possivel_item_nao_elegivel": "boquilha" in nomes,
        "observacao": "Mau uso, queda, umidade e reparo por terceiros não são cobertos. Em dúvida, encaminhar para a gerência.",
    }


# ---------------------------------------------------------------- escalonamento

def encaminhar_para_humano(resumo: str, contato: str = "", motivo: str = "reclamacao") -> dict:
    """Registra o caso para a equipe (manual 7.3: reclamação → registrar e encaminhar, retorno em 24h úteis)."""
    config.SESSOES.mkdir(exist_ok=True)
    registro = {"quando": datetime.now().isoformat(timespec="seconds"), "motivo": motivo, "contato": contato,
                "resumo": resumo}
    with open(config.SESSOES / "encaminhamentos.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {"registrado": True, "retorno_em": "até 24 horas úteis"}


# ---------------------------------------------------------------- schemas para o LLM

FERRAMENTAS = {
    "buscar_produtos": buscar_produtos,
    "detalhes_produto": detalhes_produto,
    "consultar_politicas": consultar_politicas,
    "horario_da_loja_agora": horario_da_loja_agora,
    "simular_pagamento": simular_pagamento,
    "consultar_pedidos": consultar_pedidos,
    "avaliar_devolucao": avaliar_devolucao,
    "encaminhar_para_humano": encaminhar_para_humano,
}


def _schema(nome: str, descricao: str, props: dict, obrigatorios: list[str]) -> dict:
    return {"name": nome, "description": descricao,
            "input_schema": {"type": "object", "properties": props, "required": obrigatorios}}


_CATEGORIAS = [
    "Guitarras", "Baixos", "Baterias e Percussão", "Teclados e Pianos", "Violões",
    "Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)", "Cordas Orquestrais", "Ukuleles",
]

SCHEMAS = [
    _schema(
        "buscar_produtos",
        "Busca no catálogo real (preço, estoque, promoção, especificações). Use SEMPRE antes de falar de "
        "preço, estoque ou disponibilidade. Por padrão só traz o que está disponível para compra.",
        {
            "consulta": {"type": "string", "description": "marca/modelo/características, ex.: 'takamine gd20', 'nylon'. "
                         "Não repita a categoria aqui."},
            "categoria": {"type": "string", "enum": _CATEGORIAS},
            "preco_min": {"type": "number"},
            "preco_max": {"type": "number", "description": "em reais"},
            "incluir_indisponiveis": {"type": "boolean", "description": "true quando o cliente pergunta de um "
                                      "produto específico, para poder explicar que está esgotado/descontinuado"},
            "limite": {"type": "integer"},
        },
        [],
    ),
    _schema("detalhes_produto", "Descrição completa de um produto pelo produto_id.",
            {"produto_id": {"type": "integer"}}, ["produto_id"]),
    _schema(
        "consultar_politicas",
        "Texto oficial do manual da loja. Tópicos: sobre (endereço, telefone, escopo), horario, pagamento, "
        "trocas, frete, promocoes, atendimento, garantia, privacidade.",
        {"topico": {"type": "string", "enum": _TOPICOS}}, ["topico"],
    ),
    _schema("horario_da_loja_agora", "Data/hora atual em Campo Grande e se a loja está aberta neste momento.", {}, []),
    _schema(
        "simular_pagamento",
        "Calcula PIX (5% off), parcelas sem juros válidas e frete para um valor. Use em vez de fazer contas. "
        "em_promocao=true se o preço já é promocional (PIX não tem desconto extra).",
        {"valor": {"type": "number"}, "em_promocao": {"type": "boolean"}}, ["valor"],
    ),
    _schema(
        "consultar_pedidos",
        "Status, itens, rastreio e previsão de pedidos do cliente. EXIGE o e-mail ou telefone do cadastro "
        "(verificação de identidade). Nunca revele dados sem passar por aqui.",
        {"contato": {"type": "string", "description": "e-mail ou telefone com DDD informado pelo cliente"},
         "pedido_id": {"type": "integer", "description": "opcional; sem ele lista todos os pedidos do cliente"}},
        ["contato"],
    ),
    _schema(
        "avaliar_devolucao",
        "Verifica se um pedido está dentro dos prazos de arrependimento, troca por preferência ou defeito. "
        "EXIGE contato verificado e número do pedido.",
        {"contato": {"type": "string"}, "pedido_id": {"type": "integer"},
         "motivo": {"type": "string", "enum": ["arrependimento", "preferencia", "defeito"]}},
        ["contato", "pedido_id", "motivo"],
    ),
    _schema(
        "encaminhar_para_humano",
        "Registra reclamação ou caso que o agente não resolve (cancelamento, exceções, dúvida de política) "
        "para a equipe, que retorna em até 24h úteis.",
        {"resumo": {"type": "string"}, "contato": {"type": "string"},
         "motivo": {"type": "string", "enum": ["reclamacao", "cancelamento", "excecao_de_politica", "outro"]}},
        ["resumo"],
    ),
]


def executar(nome: str, argumentos: dict) -> str:
    """Roda a ferramenta e devolve JSON; erros viram resultado para o modelo se corrigir."""
    try:
        return json.dumps(FERRAMENTAS[nome](**argumentos), ensure_ascii=False)
    except Exception as e:  # argumento inválido do modelo, dado inesperado etc.
        return json.dumps({"erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
