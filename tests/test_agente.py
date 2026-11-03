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


def test_falha_da_api_nao_corrompe_historico(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)

    class Quebrado:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("API fora")

    a = Agente("q", cliente=Quebrado())
    try:
        a.responder("oi")
    except RuntimeError:
        pass
    assert a.mensagens == []


def test_historico_e_aparado_sem_separar_tool_use(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("emporio.config.MAX_MENSAGENS", 6)
    a = Agente(cliente=ClienteFalso())
    a.mensagens = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": [{"type": "text", "text": "a"}]}] * 6
    a._aparar()
    assert a.mensagens[0]["role"] == "user" and isinstance(a.mensagens[0]["content"], str)
    assert len(a.mensagens) < 12
