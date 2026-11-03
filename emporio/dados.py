"""Carga e limpeza dos CSVs. Tudo em memória: são ~190 linhas."""
import csv
import json
import re
import unicodedata
from functools import lru_cache

from .config import DADOS

STATUS_PEDIDO = {
    "pending": "aguardando confirmação de pagamento",
    "confirmed": "confirmado, em preparação",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
STATUS_PRODUTO = {"active": "ativo", "discontinued": "descontinuado", "coming_soon": "em breve"}


def normalizar(texto: str) -> str:
    """minúsculas e sem acento, para comparar buscas."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _ler(nome: str) -> list[dict]:
    with open(DADOS / f"desafio_tecnico_ai_eng - {nome}.csv", encoding="utf-8", newline="") as f:
        return [{k: v.strip() for k, v in linha.items()} for linha in csv.DictReader(f)]


@lru_cache(maxsize=1)
def carregar() -> dict:
    categorias = {int(c["category_id"]): c["name"] for c in _ler("categories")}

    # promoção só vale se is_active=1; se houver mais de uma, vale a maior (não são cumulativas)
    promos: dict[int, dict] = {}
    for p in _ler("promotions"):
        if p["is_active"] != "1":
            continue
        pid = int(p["product_id"])
        desc = float(p["discount_percent"])
        if pid not in promos or desc > promos[pid]["percentual"]:
            promos[pid] = {"percentual": desc, "campanha": p["description"]}

    produtos = {}
    for p in _ler("products"):
        pid = int(p["product_id"])
        preco = float(p["price_brl"])
        estoque = int(p["stock_quantity"])
        promo = promos.get(pid)
        produtos[pid] = {
            "id": pid,
            "nome": p["name"],
            "categoria": categorias[int(p["category_id"])],
            "preco_tabela": preco,
            "promocao": (
                {**promo, "preco_promocional": round(preco * (1 - promo["percentual"] / 100), 2)}
                if promo
                else None
            ),
            "status": p["status"],
            "estoque": estoque,
            # vendável = ativo e com estoque. "coming_soon" tem estoque mas ainda não vende.
            "disponivel": p["status"] == "active" and estoque > 0,
            "descricao": p["description"],
            "specs": json.loads(p["specs"]) if p["specs"] else {},
        }

    clientes = {
        int(c["customer_id"]): {
            "id": int(c["customer_id"]),
            "nome": c["name"],
            "telefone": so_digitos(c["phone"]),
            "email": c["email"].lower(),
            "cidade": c["city"],
        }
        for c in _ler("customers")
    }

    itens: dict[int, list[dict]] = {}
    for i in _ler("order_items"):
        itens.setdefault(int(i["order_id"]), []).append(
            {"produto_id": int(i["product_id"]), "quantidade": int(i["quantity"])}
        )

    pedidos = {}
    for o in _ler("orders"):
        oid = int(o["order_id"])
        pedidos[oid] = {
            "id": oid,
            "cliente_id": int(o["customer_id"]),
            "data": o["order_date"],
            "status": o["status"],
            "total": float(o["total_brl"]),
            "pagamento": o["payment_method"],
            "rastreio": o["tracking_code"] or None,
            "previsao_entrega": o["estimated_delivery"] or None,
            "observacao": o["notes"] or None,
            "itens": itens.get(oid, []),
        }

    return {"categorias": categorias, "produtos": produtos, "clientes": clientes, "pedidos": pedidos}
