"""Uso: python -m emporio [--sessao NOME] [--verbose] [--transcricao ARQUIVO.md]"""
import argparse

from dotenv import load_dotenv

from . import config
from .agente import Agente


def main():
    load_dotenv(config.RAIZ / ".env")
    ap = argparse.ArgumentParser(prog="emporio")
    ap.add_argument("--sessao", help="nome da sessão; guarda e retoma o histórico em .sessions/")
    ap.add_argument("--verbose", action="store_true", help="mostra as ferramentas chamadas")
    ap.add_argument("--transcricao", help="salva a conversa em markdown neste arquivo")
    args = ap.parse_args()

    agente = Agente(args.sessao, verbose=args.verbose)
    print("Empório da Música: atendimento (Ctrl+C ou 'sair' para encerrar)\n")
    transcricao = []
    try:
        while (texto := input("Você: ").strip()) not in ("sair", "exit"):
            if not texto:
                continue
            resposta = agente.responder(texto)
            print(f"\nMelô: {resposta}\n")
            transcricao += [f"**Cliente:** {texto}\n", f"**Melô:** {resposta}\n"]
    except (KeyboardInterrupt, EOFError):
        print()
    if args.transcricao and transcricao:
        with open(args.transcricao, "w", encoding="utf-8") as f:
            f.write("\n".join(transcricao))


if __name__ == "__main__":
    main()
