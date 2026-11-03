import os
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
SESSOES = RAIZ / ".sessions"

MODELO = os.getenv("EMPORIO_MODEL", "claude-haiku-5-5")
MAX_ITERACOES_TOOLS = 6

# Os CSVs são um retrato congelado (último pedido: 2026-03-22). Usar o relógio real
# faria todo prazo de troca parecer vencido, então o "hoje" do agente é configurável.
HOJE = date.fromisoformat(os.getenv("EMPORIO_HOJE", "2026-03-23"))
FUSO = "America/Campo_Grande"
