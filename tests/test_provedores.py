import json
from types import SimpleNamespace as NS

import anthropic

try:  # versões novas do SDK usam httpx2
    import httpx2 as httpx
except ImportError:
    import httpx

from emporio import config
from emporio.agente import Agente
from emporio.modelos import ModeloAnthropic, _para_anthropic

HISTORICO = [
    {"role": "user", "content": "Quanto custa o GD20 e a Yamaha C40?"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "buscar_produtos", "arguments": '{"consulta": "gd20"}'}},
        {"id": "b", "type": "function", "function": {"name": "buscar_produtos", "arguments": '{"consulta": "c40"}'}},
    ]},
    {"role": "tool", "tool_call_id": "a", "content": '{"preco": 2199}'},
    {"role": "tool", "tool_call_id": "b", "content": '{"preco": 599.9}'},
    {"role": "assistant", "content": "GD20: R$ 2.199; C40: R$ 599,90."},
]


def test_historico_vira_blocos_da_anthropic():
    m = _para_anthropic(HISTORICO)
    assert [x["role"] for x in m] == ["user", "assistant", "user", "assistant"]
    assert [b["type"] for b in m[1]["content"]] == ["tool_use", "tool_use"]
    assert m[1]["content"][0]["input"] == {"consulta": "gd20"}
    # os dois resultados de ferramenta precisam ir na MESMA mensagem de usuário
    assert [b["tool_use_id"] for b in m[2]["content"]] == ["a", "b"]
    assert m[3]["content"] == [{"type": "text", "text": "GD20: R$ 2.199; C40: R$ 599,90."}]


def _cliente_anthropic_com_servidor_falso(respostas, capturas):
    """Cliente REAL do SDK da Anthropic, com transporte HTTP falso: valida o que sai pela rede."""

    def handler(request: httpx.Request):
        capturas.append(json.loads(request.content))
        return httpx.Response(200, json=respostas[len(capturas) - 1])

    return anthropic.Anthropic(api_key="chave-falsa", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _msg(*content, stop="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": list(content),
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_loop_completo_com_sdk_da_anthropic(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    capturas = []
    cliente = _cliente_anthropic_com_servidor_falso([
        _msg({"type": "tool_use", "id": "toolu_1", "name": "buscar_produtos", "input": {"consulta": "takamine gd20"}},
             stop="tool_use"),
        _msg({"type": "text", "text": "Custa R$ 2.199."}),
    ], capturas)
    agente = Agente("anth", modelo=ModeloAnthropic(cliente))
    assert agente.responder("Quanto custa o Takamine GD20?") == "Custa R$ 2.199."
    assert agente.ferramentas_da_rodada == ["buscar_produtos"]

    primeira, segunda = capturas
    assert primeira["model"] == config.MODELO
    assert primeira["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in primeira["tools"]} >= {"buscar_produtos", "consultar_politicas", "avaliar_devolucao"}
    assert primeira["messages"] == [{"role": "user", "content": "Quanto custa o Takamine GD20?"}]
    resultado = segunda["messages"][-1]
    assert resultado["role"] == "user" and resultado["content"][0]["tool_use_id"] == "toolu_1"
    assert '"preco_tabela": 2199' in resultado["content"][0]["content"]
    # histórico fica no formato neutro e pode ser salvo
    assert agente.mensagens[1]["tool_calls"][0]["function"]["name"] == "buscar_produtos"


def test_trava_de_encaminhamento_tambem_vale_na_anthropic(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("emporio.ferramentas.config.SESSOES", tmp_path)
    capturas = []
    cliente = _cliente_anthropic_com_servidor_falso([
        _msg({"type": "text", "text": "Vou encaminhar para a equipe!"}),
        _msg({"type": "tool_use", "id": "t9", "name": "encaminhar_para_humano", "input": {"resumo": "x"}}, stop="tool_use"),
        _msg({"type": "text", "text": "Pronto, a equipe retorna em 24h úteis."}),
    ], capturas)
    assert Agente(modelo=ModeloAnthropic(cliente)).responder("tarraxa solta").startswith("Pronto")
    assert "[sistema]" in capturas[1]["messages"][-1]["content"]


def test_provedor_detectado_pelas_chaves(monkeypatch):
    for v in ("EMPORIO_PROVEDOR", "EMPORIO_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert config._provedor() == "anthropic"  # padrão
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert config._provedor() == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("EMPORIO_API_KEY", "y")
    assert config._provedor() == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert config._provedor() == "anthropic"
    monkeypatch.setenv("EMPORIO_PROVEDOR", "openai")
    assert config._provedor() == "openai"
