from datetime import datetime
from zoneinfo import ZoneInfo

from emporio import ferramentas as f

FUSO = ZoneInfo("America/Campo_Grande")


def test_preco_takamine_gd20():
    r = f.buscar_produtos("takamine gd20")
    assert r["total_encontrado"] == 1
    assert r["produtos"][0]["preco_tabela"] == 2199


def test_violoes_ate_1000_so_disponiveis_e_dentro_do_preco():
    r = f.buscar_produtos(categoria="Violões", preco_max=1000)
    assert r["produtos"]
    assert all(p["disponivel_para_compra"] for p in r["produtos"])
    assert all((p["promocao_ativa"] or {}).get("preco_promocional", p["preco_tabela"]) <= 1000 for p in r["produtos"])


def test_esgotado_so_aparece_se_pedido():
    assert f.buscar_produtos("giannini gf-3d")["total_encontrado"] == 0
    r = f.buscar_produtos("giannini gf-3d", incluir_indisponiveis=True)
    assert r["produtos"][0]["disponivel_para_compra"] is False


def test_promocao_inativa_e_ignorada():
    # produto 93 só tem promoções com is_active=0
    assert f.detalhes_produto(93)["promocao_ativa"] is None


def test_promocao_ativa_calcula_preco():
    p = f.detalhes_produto(121)["promocao_ativa"]
    assert p["percentual"] == 20 and p["preco_promocional"] < f.detalhes_produto(121)["preco_tabela"]


def test_pedido_exige_dono():
    # pedido 1 é do cliente 3; o contato do cliente 1 não pode vê-lo
    r = f.consultar_pedidos("lucas.mendes@jmail.com", 1)
    assert "erro" in r and "codigo_de_rastreio" not in str(r)


def test_pedido_do_dono_por_email_e_por_telefone():
    a = f.consultar_pedidos("lucas.mendes@jmail.com", 4)
    b = f.consultar_pedidos("(67) 99812-3456", 4)
    assert a["pedidos"][0]["codigo_de_rastreio"] == "BRQM7890123BR" == b["pedidos"][0]["codigo_de_rastreio"]


def test_contato_ambiguo_pede_telefone():
    assert "ambíguo" in f.consultar_pedidos("bruno.martins@jmail.com")["erro"]


def test_resposta_nao_vaza_dados_pessoais():
    r = str(f.consultar_pedidos("lucas.mendes@jmail.com"))
    assert "99812" not in r and "jmail" not in r


def test_devolucao_arrependimento_fora_do_prazo():
    r = f.avaliar_devolucao("lucas.mendes@jmail.com", 4, "arrependimento")
    assert r["regra_aplicavel"]["dentro_do_prazo"] is False


def test_devolucao_de_pedido_alheio():
    r = f.avaliar_devolucao("(67) 99812-3456", 1, "arrependimento")
    assert "erro" in r  # pedido 1 não é do Lucas


def test_pagamento_pix_e_parcelas():
    r = f.simular_pagamento(2199)
    assert r["pix_a_vista"] == 2089.05 and r["frete_campo_grande_e_regiao"] == 0
    assert max(p["parcelas"] for p in r["credito_sem_juros"]) == 12
    promo = f.simular_pagamento(2199, em_promocao=True)
    assert promo["pix_a_vista"] == 2199


def test_parcela_minima():
    r = f.simular_pagamento(300)
    assert max(p["parcelas"] for p in r["credito_sem_juros"]) == 3  # 4x seria R$ 75 < R$ 80
    assert f.simular_pagamento(450)["frete_campo_grande_e_regiao"] == 35


def test_horario():
    seg = datetime(2026, 3, 23, 10, 0, tzinfo=FUSO)
    sab_tarde = datetime(2026, 3, 28, 14, 0, tzinfo=FUSO)
    dom = datetime(2026, 3, 29, 10, 0, tzinfo=FUSO)
    assert f.horario_da_loja_agora(seg)["loja_aberta"]
    assert not f.horario_da_loja_agora(sab_tarde)["loja_aberta"]
    assert not f.horario_da_loja_agora(dom)["loja_aberta"]


def test_politicas():
    assert "5%" in f.consultar_politicas("pagamento")["texto"]
    assert "erro" in f.consultar_politicas("inexistente")


def test_executar_nao_estoura_com_argumento_errado():
    assert "erro" in f.executar("buscar_produtos", {"campo_inventado": 1})


def test_devolucao_pedido_cancelado():
    from emporio.dados import carregar
    db = carregar()
    email = db["clientes"][db["pedidos"][17]["cliente_id"]]["email"]
    assert "já cancelado" in f.avaliar_devolucao(email, 17, "arrependimento")["situacao"]


def _email(pedido_id):
    from emporio.dados import carregar
    db = carregar()
    return db["clientes"][db["pedidos"][pedido_id]["cliente_id"]]["email"]


def test_email_repetido_e_desempatado_pelo_dono_do_pedido():
    r = f.consultar_pedidos("bruno.martins@jmail.com", 10)  # pedido do Bruno Carvalho Martins
    assert r["pedidos"][0]["pedido_id"] == 10
    assert "erro" in f.consultar_pedidos("bruno.martins@jmail.com", 1)  # pedido de outra pessoa


def test_pedido_enviado_com_previsao_vencida_gera_alerta():
    alertas = f.consultar_pedidos(_email(8), 8)["pedidos"][0]["alertas"]
    assert any("venceu" in a for a in alertas)


def test_pedido_confirmado_parado_gera_alerta():
    assert any("não enviado" in a for a in f.consultar_pedidos(_email(9), 9)["pedidos"][0]["alertas"])


def test_item_em_breve_em_pedido_aberto_gera_alerta():
    assert any("em breve" in a for a in f.consultar_pedidos(_email(14), 14)["pedidos"][0]["alertas"])


def test_total_diferente_da_soma_gera_alerta():
    assert any("difere" in a for a in f.consultar_pedidos(_email(3), 3)["pedidos"][0]["alertas"])


def test_pedido_normal_sem_alerta():
    assert f.consultar_pedidos(_email(5), 5)["pedidos"][0]["alertas"] == []


def test_defeito_apos_30_dias_cai_na_garantia_legal():
    # pedido 7: comprado em 03/02 (48 dias), recebido ~17/02 (34 dias)
    regra = f.avaliar_devolucao(_email(7), 7, "defeito")["regra_aplicavel"]
    assert regra["dentro_do_prazo"] is False and "garantia legal" in regra["caminho"]


def test_pagamento_legivel():
    assert f.consultar_pedidos(_email(4), 4)["pedidos"][0]["forma_de_pagamento"] == "boleto"
    assert "12x" in f.consultar_pedidos(_email(3), 3)["pedidos"][0]["forma_de_pagamento"]
