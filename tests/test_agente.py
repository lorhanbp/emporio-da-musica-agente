from types import SimpleNamespace as NS

from google.genai import types

from emporio.agente import Agente


def _resp(*parts):
    return NS(candidates=[NS(content=types.Content(role="model", parts=list(parts)))])


class ClienteFalso:
    """Primeiro turno pede uma ferramenta, segundo responde com o resultado."""

    def __init__(self):
        self.chamadas = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.chamadas.append(list(contents))
        if len(self.chamadas) == 1:
            return _resp(types.Part.from_function_call(name="buscar_produtos", args={"consulta": "takamine gd20"}))
        return _resp(types.Part(text="Custa R$ 2.199."))


class ClienteQuebrado:
    def __init__(self):
        self.models = self

    def generate_content(self, **kw):
        raise RuntimeError("API fora")


def test_loop_executa_ferramenta_e_devolve_texto(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    cliente = ClienteFalso()
    a = Agente("teste", cliente=cliente)
    assert a.responder("Quanto custa o Takamine GD20?") == "Custa R$ 2.199."
    resposta_ferramenta = cliente.chamadas[1][-1].parts[0].function_response
    assert resposta_ferramenta.name == "buscar_produtos"
    assert resposta_ferramenta.response["resultado"]["produtos"][0]["preco_tabela"] == 2199


def test_historico_persiste_entre_sessoes(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    Agente("s1", cliente=ClienteFalso()).responder("oi")
    assert len(Agente("s1", cliente=ClienteFalso()).mensagens) == 4


def test_falha_da_api_nao_corrompe_historico(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    a = Agente("q", cliente=ClienteQuebrado())
    try:
        a.responder("oi")
    except RuntimeError:
        pass
    assert a.mensagens == []


def test_historico_e_aparado_sem_separar_chamada_de_resposta(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.MAX_MENSAGENS", 6)
    a = Agente(cliente=ClienteFalso())
    fala = types.Content(role="user", parts=[types.Part(text="u")])
    modelo = types.Content(role="model", parts=[types.Part(text="a")])
    a.mensagens = [fala, modelo] * 6
    a._aparar()
    assert a.mensagens[0].role == "user" and len(a.mensagens) < 12


def test_espera_e_tenta_de_novo_em_429(tmp_path, monkeypatch):
    from google.genai import errors

    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("time.sleep", lambda s: None)

    class Limitado(ClienteFalso):
        def generate_content(self, model, contents, config):
            self.n = getattr(self, "n", 0) + 1
            if self.n == 1:
                raise errors.ClientError(429, {"error": {"message": "Please retry in 5s", "status": "RESOURCE_EXHAUSTED"}})
            return _resp(types.Part(text="ok"))

    assert Agente(cliente=Limitado()).responder("oi") == "ok"


def test_cobra_ferramenta_quando_promete_encaminhar_sem_chamar(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)

    class Prometedor(ClienteFalso):
        def generate_content(self, model, contents, config):
            self.chamadas.append(list(contents))
            n = len(self.chamadas)
            if n == 1:
                return _resp(types.Part(text="Vou encaminhar para a equipe!"))
            if n == 2:  # após a cobrança, chama a ferramenta
                return _resp(types.Part.from_function_call(name="encaminhar_para_humano", args={"resumo": "x"}))
            return _resp(types.Part(text="Pronto, a equipe retorna em 24h úteis."))

    monkeypatch.setattr("emporio.ferramentas.config.SESSOES", tmp_path)
    cliente = Prometedor()
    assert Agente(cliente=cliente).responder("tarraxa solta").startswith("Pronto")
    assert "[sistema]" in cliente.chamadas[1][-1].parts[0].text
    assert (tmp_path / "encaminhamentos.jsonl").exists()


def test_nao_cobra_quando_ja_chamou_a_ferramenta(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio.config.SESSOES", tmp_path)
    monkeypatch.setattr("emporio.ferramentas.config.SESSOES", tmp_path)

    class Certo(ClienteFalso):
        def generate_content(self, model, contents, config):
            self.chamadas.append(list(contents))
            if len(self.chamadas) == 1:
                return _resp(types.Part.from_function_call(name="encaminhar_para_humano", args={"resumo": "x"}))
            return _resp(types.Part(text="Encaminhei para a equipe."))

    cliente = Certo()
    assert Agente(cliente=cliente).responder("oi") == "Encaminhei para a equipe."
    assert len(cliente.chamadas) == 2
