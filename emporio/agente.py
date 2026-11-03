import json
import os
import re

from openai import OpenAI

from . import config
from .ferramentas import SCHEMAS, executar
from .prompt import SYSTEM

_TOOLS = [
    {"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
    for s in SCHEMAS
]
_PROMETEU_ENCAMINHAR = re.compile(r"\b(encaminh|registr)\w*", re.I)
_COBRANCA = (
    "[sistema] Sua resposta diz que encaminhou ou registrou algo, mas você não chamou "
    "`encaminhar_para_humano` nesta conversa. Chame a ferramenta agora; se não for o caso, "
    "reescreva a resposta sem prometer essa ação."
)


class Agente:
    """Loop de function calling sobre uma API compatível com OpenAI (DeepSeek por padrão).
    O histórico fica em disco por sessão."""

    def __init__(self, sessao: str | None = None, cliente: OpenAI | None = None, verbose=False):
        self.cliente = cliente or OpenAI(
            api_key=os.getenv("EMPORIO_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
            base_url=config.BASE_URL,
            max_retries=4,  # o SDK espera e repete em 429/5xx
        )
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
            r = self.cliente.chat.completions.create(
                model=config.MODELO,
                messages=[{"role": "system", "content": SYSTEM}, *self.mensagens],
                tools=_TOOLS,
                temperature=0.3,
            )
            msg = r.choices[0].message
            # model_dump mantém campos extras (ex.: reasoning_content), que a DeepSeek exige de volta nos turnos com ferramenta
            self.mensagens.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                final = (msg.content or "").strip()
                # Trava: dizer "encaminhei" sem chamar a ferramenta é prometer uma ação que não aconteceu.
                if _PROMETEU_ENCAMINHAR.search(final) and "encaminhar_para_humano" not in chamou and not cobrou:
                    cobrou = True
                    self.mensagens.append({"role": "user", "content": _COBRANCA})
                    continue
                return final or None
            for c in msg.tool_calls:
                chamou.add(c.function.name)
                self.ferramentas_da_rodada.append(c.function.name)
                try:
                    args = json.loads(c.function.arguments or "{}")
                    saida = executar(c.function.name, args)
                except json.JSONDecodeError:
                    args, saida = c.function.arguments, json.dumps({"erro": "argumentos não são JSON válido"}, ensure_ascii=False)
                if self.verbose:
                    print(f"  [tool] {c.function.name}({args}) -> {saida[:300]}")
                self.mensagens.append({"role": "tool", "tool_call_id": c.id, "content": saida})
        return None
