import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
SESSOES = RAIZ / ".sessions"

load_dotenv(RAIZ / ".env")  # antes das leituras abaixo

MODELO = os.getenv("EMPORIO_MODEL", "gemini-2.5-flash")
MAX_ITERACOES_TOOLS = 6
MAX_TENTATIVAS = 5  # tentativas por chamada ao modelo (429/503)
MAX_MENSAGENS = 40  # histórico enviado ao modelo; o mais antigo é descartado

# Os CSVs são um retrato congelado (último pedido: 2026-03-22). Usar o relógio real
# faria todo prazo de troca parecer vencido, então o "hoje" do agente é configurável.
HOJE = date.fromisoformat(os.getenv("EMPORIO_HOJE", "2026-03-23"))
FUSO = "America/Campo_Grande"
