import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
SESSOES = RAIZ / ".sessions"

load_dotenv(RAIZ / ".env")  # antes das leituras abaixo



def _provedor() -> str:
    """EMPORIO_PROVEDOR manda; senão, só ANTHROPIC_API_KEY presente => anthropic; senão deepseek."""
    p = os.getenv("EMPORIO_PROVEDOR")
    if p:
        return p.lower()
    tem_deepseek = os.getenv("DEEPSEEK_API_KEY") or os.getenv("EMPORIO_API_KEY")
    return "anthropic" if os.getenv("ANTHROPIC_API_KEY") and not tem_deepseek else "deepseek"


PROVEDOR = _provedor()
MODELO = os.getenv("EMPORIO_MODEL") or ("claude-haiku-5-5" if PROVEDOR == "anthropic" else "deepseek-flash")
VARIAVEL_DA_CHAVE = "ANTHROPIC_API_KEY" if PROVEDOR == "anthropic" else "DEEPSEEK_API_KEY"


def tem_chave() -> bool:
    return bool(os.getenv(VARIAVEL_DA_CHAVE) or (PROVEDOR != "anthropic" and os.getenv("EMPORIO_API_KEY")))


BASE_URL = os.getenv("EMPORIO_BASE_URL", "https://api.deepseek.com")
MAX_ITERACOES_TOOLS = 6
MAX_MENSAGENS = 40  # histórico enviado ao modelo; o mais antigo é descartado

# Os CSVs são um retrato congelado (último pedido: 2026-03-22). Usar o relógio real
# faria todo prazo de troca parecer vencido, então o "hoje" do agente é configurável.
HOJE = date.fromisoformat(os.getenv("EMPORIO_HOJE", "2026-03-23"))
FUSO = "America/Campo_Grande"
