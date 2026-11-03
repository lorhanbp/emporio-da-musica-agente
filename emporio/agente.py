import json
import re

from . import config, modelos
from .ferramentas import executar
from .prompt import SYSTEM

_PROMETEU_ENCAMINHAR = re.compile(r"\b(encaminh|registr)\w*", re.I)
_COBRANCA = (
    "[sistema] Sua resposta diz que encaminhou ou registrou algo, mas você não chamou "
    "`encaminhar_para_humano` nesta conversa. Chame a ferramenta agora; se não for o caso, "
    "reescreva a resposta sem prometer essa ação."
)


class Agente:
    """Loop de function calling, independente de provedor (ver modelos.py). O histórico fica em disco por sessão."""

    def __init__(self, sessao: str | None = None, modelo=None, verbose=False):
        self.modelo = modelo or modelos.criar()
        self.verbose = verbose
        self.ferramentas_da_rodada: list[str] = []
        self.arquivo = None
        self.mensagens: list[dict] = []
        if sessao:
            config.SESSOES.mkdir(exist_ok=True)
            nome = re.sub(r"[^\w-]", "_", sessao)
            self.arquivo = config.SESSOES / f"{nome}.json"
            if self.arquivo.exists():
                self.mensagens = json.loads(self.arquivo.read_text(encoding="utf-8"))

    def _salvar(self):
        if self.arquivo:
            self.arquivo.write_text(json.dumps(self.mensagens, ensure_ascii=False), encoding="utf-8")

    def _aparar(self):
        """Limita o histórico, cortando só em falas do usuário para não separar tool_calls das respostas."""
        if len(self.mensagens) <= config.MAX_MENSAGENS:
            return
        for i in range(len(self.mensagens) - config.MAX_MENSAGENS // 2, len(self.mensagens)):
            if self.mensagens[i]["role"] == "user":
                self.mensagens = self.mensagens[i:]
                return

    def responder(self, texto: str) -> str:
        """Em qualquer falha (API fora, limite de ferramentas) o histórico volta ao estado anterior."""
        self._aparar()
        estado = list(self.mensagens)
        try:
            resposta = self._turno(texto)
        except BaseException:
            self.mensagens = estado
            raise
        if resposta is None:
            self.mensagens = estado
            resposta = "Desculpa, me enrolei aqui. Pode repetir a pergunta ou chamar a gente no (67) 3341-4444?"
        self._salvar()
        return resposta

    def _turno(self, texto: str) -> str | None:
        self.mensagens.append({"role": "user", "content": texto})
        chamou, cobrou = set(), False
        self.ferramentas_da_rodada = []
        for _ in range(config.MAX_ITERACOES_TOOLS):
            r = self.modelo.gerar(SYSTEM, self.mensagens)
            self.mensagens.append(r.mensagem)
            if not r.chamadas:
                # Trava: dizer "encaminhei" sem chamar a ferramenta é prometer uma ação que não aconteceu.
                if _PROMETEU_ENCAMINHAR.search(r.texto) and "encaminhar_para_humano" not in chamou and not cobrou:
                    cobrou = True
                    self.mensagens.append({"role": "user", "content": _COBRANCA})
                    continue
                return r.texto or None
            for id_chamada, nome, argumentos in r.chamadas:
                chamou.add(nome)
                self.ferramentas_da_rodada.append(nome)
                try:
                    args = json.loads(argumentos)
                    saida = executar(nome, args)
                except json.JSONDecodeError:
                    args, saida = argumentos, json.dumps({"erro": "argumentos não são JSON válido"}, ensure_ascii=False)
                if self.verbose:
                    print(f"  [tool] {nome}({args}) -> {saida[:300]}")
                self.mensagens.append({"role": "tool", "tool_call_id": id_chamada, "content": saida})
        return None
