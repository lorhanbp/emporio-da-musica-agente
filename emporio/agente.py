import json
import re

import anthropic

from . import config
from .ferramentas import SCHEMAS, executar
from .prompt import SYSTEM


def _bloco(b) -> dict:
    if b.type == "text":
        return {"type": "text", "text": b.text}
    return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}


class Agente:
    """Loop de function calling sobre a API de mensagens. O histórico fica em disco por sessão."""

    def __init__(self, sessao: str | None = None, cliente: anthropic.Anthropic | None = None, verbose=False):
        self.cliente = cliente or anthropic.Anthropic()
        self.verbose = verbose
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
        """Limita o histórico, cortando só em turnos de texto do usuário para não separar tool_use de tool_result."""
        if len(self.mensagens) <= config.MAX_MENSAGENS:
            return
        for i in range(len(self.mensagens) - config.MAX_MENSAGENS // 2, len(self.mensagens)):
            if self.mensagens[i]["role"] == "user" and isinstance(self.mensagens[i]["content"], str):
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
        for _ in range(config.MAX_ITERACOES_TOOLS):
            r = self.cliente.messages.create(
                model=config.MODELO,
                max_tokens=1024,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                tools=SCHEMAS,
                messages=self.mensagens,
            )
            self.mensagens.append({"role": "assistant", "content": [_bloco(b) for b in r.content]})
            if r.stop_reason != "tool_use":
                return "".join(b.text for b in r.content if b.type == "text").strip()
            resultados = []
            for b in r.content:
                if b.type != "tool_use":
                    continue
                saida = executar(b.name, b.input)
                if self.verbose:
                    print(f"  [tool] {b.name}({json.dumps(b.input, ensure_ascii=False)}) -> {saida[:300]}")
                resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": saida})
            self.mensagens.append({"role": "user", "content": resultados})
        return None
