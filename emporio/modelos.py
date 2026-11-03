"""Adaptadores de provedor de LLM.

O histórico do agente fica sempre no formato OpenAI (role/tool_calls/tool). Cada adaptador traduz
para a API do seu provedor e devolve uma `Resposta` neutra, então o loop do agente não muda.
"""
import json
import os
from dataclasses import dataclass

from . import config
from .ferramentas import SCHEMAS


@dataclass
class Resposta:
    mensagem: dict  # entra no histórico
    texto: str
    chamadas: list  # [(id, nome, argumentos_json)]


class ModeloOpenAI:
    """DeepSeek (padrão) ou qualquer API compatível com OpenAI."""

    def __init__(self, cliente=None):
        if cliente is None:
            from openai import OpenAI

            cliente = OpenAI(
                api_key=os.getenv("EMPORIO_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
                base_url=config.BASE_URL,
                max_retries=4,  # o SDK espera e repete em 429/5xx
            )
        self.cliente = cliente
        self.tools = [
            {"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
            for s in SCHEMAS
        ]

    def gerar(self, system: str, mensagens: list[dict]) -> Resposta:
        r = self.cliente.chat.completions.create(
            model=config.MODELO,
            messages=[{"role": "system", "content": system}, *mensagens],
            tools=self.tools,
            temperature=0.3,
        )
        msg = r.choices[0].message
        # model_dump mantém campos extras (ex.: reasoning_content), que a DeepSeek exige de volta nos turnos com ferramenta
        return Resposta(
            msg.model_dump(exclude_none=True),
            (msg.content or "").strip(),
            [(c.id, c.function.name, c.function.arguments or "{}") for c in msg.tool_calls or []],
        )


def _para_anthropic(mensagens: list[dict]) -> list[dict]:
    """Histórico no formato OpenAI -> blocos de conteúdo da API de mensagens da Anthropic."""
    saida: list[dict] = []
    for m in mensagens:
        if m["role"] == "tool":
            bloco = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if saida and saida[-1]["role"] == "user" and isinstance(saida[-1]["content"], list):
                saida[-1]["content"].append(bloco)  # resultados de várias ferramentas vão juntos
            else:
                saida.append({"role": "user", "content": [bloco]})
        elif m["role"] == "assistant":
            blocos = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for c in m.get("tool_calls") or []:
                try:
                    entrada = json.loads(c["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    entrada = {}
                blocos.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": entrada})
            saida.append({"role": "assistant", "content": blocos})
        else:
            saida.append({"role": "user", "content": m["content"]})
    return saida


class ModeloAnthropic:
    """Claude via API da Anthropic (lê ANTHROPIC_API_KEY)."""

    def __init__(self, cliente=None):
        if cliente is None:
            import anthropic

            cliente = anthropic.Anthropic(max_retries=4)
        self.cliente = cliente
        self.tools = [{"name": s["name"], "description": s["description"], "input_schema": s["input_schema"]} for s in SCHEMAS]

    def gerar(self, system: str, mensagens: list[dict]) -> Resposta:
        r = self.cliente.messages.create(
            model=config.MODELO,
            max_tokens=2048,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=self.tools,
            messages=_para_anthropic(mensagens),
        )
        texto = "".join(b.text for b in r.content if b.type == "text").strip()
        usos = [b for b in r.content if b.type == "tool_use"]
        chamadas = [(b.id, b.name, json.dumps(b.input, ensure_ascii=False)) for b in usos]
        mensagem = {"role": "assistant", "content": texto or None}
        if usos:
            mensagem["tool_calls"] = [
                {"id": i, "type": "function", "function": {"name": n, "arguments": a}} for i, n, a in chamadas
            ]
        return Resposta(mensagem, texto, chamadas)


def criar():
    return ModeloAnthropic() if config.PROVEDOR == "anthropic" else ModeloOpenAI()


def erros_api() -> tuple:
    """Exceções de API de cada SDK, para o CLI avisar sem derrubar a conversa."""
    erros = []
    for modulo in ("openai", "anthropic"):
        try:
            erros.append(__import__(modulo).APIError)
        except ImportError:
            pass
    return tuple(erros)
