from types import SimpleNamespace as NS

from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall, Function

from emporio.agente import Agente
from emporio.modelos import ModeloOpenAI


def _texto(t):
    return NS(choices=[NS(message=ChatCompletionMessage(role="assistant", content=t))])


def _chamada(nome, args, id="c1"):
    call = ChatCompletionMessageFunctionToolCall(id=id, type="function", function=Function(name=nome, arguments=args))
    return NS(choices=[NS(message=ChatCompletionMessage(role="assistant", content=None, tool_calls=[call]))])


class ClienteFalso:
    """Primeiro turno pede uma ferramenta, segundo responde com o resultado."""

    def __init__(self):
        self.chamadas = []
        self.chat = NS(completions=self)

    def create(self, model, messages, tools, temperature):
        self.chamadas.append(list(messages))
        if len(self.chamadas) == 1:
            return _chamada("buscar_produtos", '{"consulta": "takamine gd20"}')
        return _texto("Custa R$ 2.199.")


class ClienteQuebrado(ClienteFalso):
    def create(self, **kw):
        raise RuntimeError("API fora")


def test_loop_executa_ferramenta_e_devolve_texto(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    cliente = ClienteFalso()
    a = Agente("teste", modelo=ModeloOpenAI(cliente))
    assert a.responder("Quanto custa o Takamine GD20?") == "Custa R$ 2.199."
    ultima = cliente.chamadas[1][-1]
    assert ultima["role"] == "tool" and ultima["tool_call_id"] == "c1" and '"preco_tabela": 2199' in ultima["content"]
    assert cliente.chamadas[0][0]["role"] == "system"


def test_historico_persiste_entre_sessoes(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    Agente("s1", modelo=ModeloOpenAI(ClienteFalso())).responder("oi")
    assert len(Agente("s1", modelo=ModeloOpenAI(ClienteFalso())).mensagens) == 4  # user, assistant(tool_calls), tool, assistant


def test_falha_da_api_nao_corrompe_historico(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    a = Agente("q", modelo=ModeloOpenAI(ClienteQuebrado()))
    try:
        a.responder("oi")
    except RuntimeError:
        pass
    assert a.mensagens == []


def test_historico_e_aparado_sem_separar_chamada_de_resposta(monkeypatch):
    monkeypatch.setattr("emporio.config.MAX_MENSAGENS", 6)
    a = Agente(modelo=ModeloOpenAI(ClienteFalso()))
    a.mensagens = [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        {"role": "tool", "tool_call_id": "x", "content": "{}"},
        {"role": "assistant", "content": "a"},
    ] * 4 + [{"role": "user", "content": "u"}]
    a._aparar()
    assert a.mensagens[0]["role"] == "user" and len(a.mensagens) < 17


def test_cobra_ferramenta_quando_promete_encaminhar_sem_chamar(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("emporio.ferramentas.config.SESSOES", tmp_path)

    class Prometedor(ClienteFalso):
        def create(self, model, messages, tools, temperature):
            self.chamadas.append(list(messages))
            n = len(self.chamadas)
            if n == 1:
                return _texto("Vou encaminhar para a equipe!")
            if n == 2:  # após a cobrança, chama a ferramenta
                return _chamada("encaminhar_para_humano", '{"resumo": "x"}')
            return _texto("Pronto, a equipe retorna em 24h úteis.")

    cliente = Prometedor()
    assert Agente(modelo=ModeloOpenAI(cliente)).responder("tarraxa solta").startswith("Pronto")
    assert "[sistema]" in cliente.chamadas[1][-1]["content"]
    assert (tmp_path / "encaminhamentos.jsonl").exists()


def test_nao_cobra_quando_ja_chamou_a_ferramenta(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("emporio.ferramentas.config.SESSOES", tmp_path)

    class Certo(ClienteFalso):
        def create(self, model, messages, tools, temperature):
            self.chamadas.append(list(messages))
            if len(self.chamadas) == 1:
                return _chamada("encaminhar_para_humano", '{"resumo": "x"}')
            return _texto("Encaminhei para a equipe.")

    cliente = Certo()
    assert Agente(modelo=ModeloOpenAI(cliente)).responder("oi") == "Encaminhei para a equipe."
    assert len(cliente.chamadas) == 2


def test_argumentos_invalidos_viram_erro_para_o_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)

    class Torto(ClienteFalso):
        def create(self, model, messages, tools, temperature):
            self.chamadas.append(list(messages))
            if len(self.chamadas) == 1:
                return _chamada("buscar_produtos", "{quebrado")
            return _texto("Pode repetir?")

    cliente = Torto()
    assert Agente(modelo=ModeloOpenAI(cliente)).responder("oi") == "Pode repetir?"
    assert "não são JSON" in cliente.chamadas[1][-1]["content"]
