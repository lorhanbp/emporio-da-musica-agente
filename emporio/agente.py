import json
import os
import re
import time

from google import genai
from google.genai import errors, types

from . import config
from .ferramentas import SCHEMAS, executar
from .prompt import SYSTEM

_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=s["name"],
                description=s["description"],
                **({"parameters_json_schema": s["input_schema"]} if s["input_schema"]["properties"] else {}),
            )
            for s in SCHEMAS
        ]
    )
]


_PROMETEU_ENCAMINHAR = re.compile(r"\b(encaminh|registr)\w*", re.I)
_COBRANCA = (
    "[sistema] Sua resposta diz que encaminhou ou registrou algo, mas você não chamou "
    "`encaminhar_para_humano` nesta conversa. Chame a ferramenta agora; se não for o caso, "
    "reescreva a resposta sem prometer essa ação."
)


class Agente:
    """Loop de function calling sobre a API do Gemini. O histórico fica em disco por sessão."""

    def __init__(self, sessao: str | None = None, cliente: genai.Client | None = None, verbose=False):
        self.cliente = cliente or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.verbose = verbose
        self.arquivo = None
        self.mensagens: list[types.Content] = []
        if sessao:
            config.SESSOES.mkdir(exist_ok=True)
            nome = re.sub(r"[^\w-]", "_", sessao)
            self.arquivo = config.SESSOES / f"{nome}.json"
            if self.arquivo.exists():
                dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
                self.mensagens = [types.Content.model_validate(m) for m in dados]

    def _salvar(self):
        if self.arquivo:
            dados = [m.model_dump(mode="json", exclude_none=True) for m in self.mensagens]
            self.arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _eh_fala_do_usuario(m: types.Content) -> bool:
        return m.role == "user" and all(p.text is not None for p in m.parts or [])

    def _aparar(self):
        """Limita o histórico, cortando só em falas de texto do usuário para não separar chamada e resposta de ferramenta."""
        if len(self.mensagens) <= config.MAX_MENSAGENS:
            return
        for i in range(len(self.mensagens) - config.MAX_MENSAGENS // 2, len(self.mensagens)):
            if self._eh_fala_do_usuario(self.mensagens[i]):
                self.mensagens = self.mensagens[i:]
                return

    def _gerar(self, cfg):
        """generate_content com espera e nova tentativa em limite de cota (429) ou sobrecarga (503)."""
        for tentativa in range(config.MAX_TENTATIVAS):
            try:
                return self.cliente.models.generate_content(model=config.MODELO, contents=self.mensagens, config=cfg)
            except errors.APIError as e:
                if e.code not in (429, 503) or tentativa == config.MAX_TENTATIVAS - 1:
                    raise
                sugerido = re.search(r"retry in ([\d.]+)s", str(e))
                espera = min(float(sugerido[1]) + 1 if sugerido else 5 * (tentativa + 1), 60)
                if self.verbose:
                    print(f"  [cota/sobrecarga {e.code}] aguardando {espera:.0f}s")
                time.sleep(espera)

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
        self.mensagens.append(types.Content(role="user", parts=[types.Part(text=texto)]))
        chamou, cobrou = set(), False
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=_TOOLS,
            temperature=0.3,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for _ in range(config.MAX_ITERACOES_TOOLS):
            r = self._gerar(cfg)
            if not r.candidates or not r.candidates[0].content or not r.candidates[0].content.parts:
                return None  # bloqueio de segurança ou resposta vazia
            conteudo = r.candidates[0].content
            self.mensagens.append(conteudo)
            chamadas = [p.function_call for p in conteudo.parts if p.function_call]
            if not chamadas:
                texto_final = "".join(p.text for p in conteudo.parts if p.text and not p.thought).strip()
                # Trava: dizer "encaminhei" sem chamar a ferramenta é prometer uma ação que não aconteceu.
                if _PROMETEU_ENCAMINHAR.search(texto_final) and "encaminhar_para_humano" not in chamou and not cobrou:
                    cobrou = True
                    self.mensagens.append(types.Content(role="user", parts=[types.Part(text=_COBRANCA)]))
                    continue
                return texto_final or None
            respostas = []
            for c in chamadas:
                chamou.add(c.name)
                saida = executar(c.name, dict(c.args or {}))
                if self.verbose:
                    print(f"  [tool] {c.name}({json.dumps(dict(c.args or {}), ensure_ascii=False)}) -> {saida[:300]}")
                respostas.append(types.Part.from_function_response(name=c.name, response={"resultado": json.loads(saida)}))
            self.mensagens.append(types.Content(role="user", parts=respostas))
        return None
