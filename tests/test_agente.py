from types import SimpleNamespace as NS

from emporio.agente import Agente


class ClienteFalso:
    """Primeiro turno pede uma ferramenta, segundo responde com o resultado."""

    def __init__(self):
        self.chamadas = []
        self.messages = self

    def create(self, **kw):
        self.chamadas.append(kw["messages"][:])
        if len(self.chamadas) == 1:
            bloco = NS(type="tool_use", id="t1", name="buscar_produtos", input={"consulta": "takamine gd20"})
            return NS(stop_reason="tool_use", content=[bloco])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Custa R$ 2.199.")])


def test_loop_executa_ferramenta_e_devolve_texto(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    cliente = ClienteFalso()
    a = Agente("teste", cliente=cliente)
    assert a.responder("Quanto custa o Takamine GD20?") == "Custa R$ 2.199."
    resultado = cliente.chamadas[1][-1]["content"][0]
    assert resultado["type"] == "tool_result" and "2199" in resultado["content"]


def test_historico_persiste_entre_sessoes(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    Agente("s1", cliente=ClienteFalso()).responder("oi")
    assert len(Agente("s1", cliente=ClienteFalso()).mensagens) == 4
