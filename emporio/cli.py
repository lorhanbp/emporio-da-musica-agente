"""Uso: python -m emporio [--sessao NOME] [--verbose] [--transcricao ARQUIVO.md]"""
import argparse
import os
import sys

import openai

from . import config
from .agente import Agente


def main():
    ap = argparse.ArgumentParser(prog="emporio")
    ap.add_argument("--sessao", help="nome da sessão; guarda e retoma o histórico em .sessions/")
    ap.add_argument("--verbose", action="store_true", help="mostra as ferramentas chamadas")
    ap.add_argument("--transcricao", help="salva a conversa em markdown neste arquivo")
    args = ap.parse_args()

    if not (os.getenv("EMPORIO_API_KEY") or os.getenv("DEEPSEEK_API_KEY")):
        sys.exit("Falta DEEPSEEK_API_KEY: copie .env.example para .env e preencha.")
    agente = Agente(args.sessao, verbose=args.verbose)
    print("Empório da Música: atendimento (Ctrl+C ou 'sair' para encerrar)\n")
    transcricao = []
    try:
        while (texto := input("Você: ").strip()) not in ("sair", "exit"):
            if not texto:
                continue
            try:
                resposta = agente.responder(texto)
            except openai.APIError as e:
                print(f"\n[erro na API: {e.__class__.__name__}] tente de novo.\n")
                continue
            print(f"\nMelô: {resposta}\n")
            transcricao += [f"**Cliente:** {texto}\n", f"**Melô:** {resposta}\n"]
    except (KeyboardInterrupt, EOFError):
        print()
    if args.transcricao and transcricao:
        with open(args.transcricao, "w", encoding="utf-8") as f:
            f.write("\n".join(transcricao))


if __name__ == "__main__":
    main()
