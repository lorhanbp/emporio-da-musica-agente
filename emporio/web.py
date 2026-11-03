"""Interface web mínima para testar a Melô no navegador. Uso: python -m emporio.web [porta]
Sobe só em 127.0.0.1 (a chave da API é sua: não exponha na internet)."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .agente import Agente

PAGINA = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Melô · Empório da Música</title>
<style>
*{box-sizing:border-box}body{margin:0;font:16px system-ui;background:#e5ddd5;display:flex;flex-direction:column;height:100vh}
header{background:#075e54;color:#fff;padding:14px 18px}header b{display:block}header small{opacity:.8}
#chat{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
.m{max-width:75%;padding:9px 12px;border-radius:10px;white-space:pre-wrap;line-height:1.35;box-shadow:0 1px 1px #0002}
.u{align-self:flex-end;background:#dcf8c6}.b{align-self:flex-start;background:#fff}
.t{font-size:12px;color:#667;margin-top:6px}
form{display:flex;gap:8px;padding:10px;background:#f0f0f0}input{flex:1;padding:12px;border:0;border-radius:20px;font:inherit}
button{border:0;border-radius:20px;background:#075e54;color:#fff;padding:0 20px;font:inherit;cursor:pointer}
button:disabled{opacity:.5}
</style>
<header><b>Melô · Empório da Música</b><small>assistente virtual (protótipo) · "hoje" = __HOJE__</small></header>
<div id=chat></div>
<form id=f><input id=i placeholder="Digite sua mensagem" autocomplete=off autofocus><button id=s>Enviar</button></form>
<script>
const sid=Math.random().toString(36).slice(2),chat=document.getElementById('chat');
const esc=t=>t.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt=t=>esc(t).replace(/\\*([^*\\n]+)\\*/g,'<b>$1</b>');
function add(cls,html,tools){const d=document.createElement('div');d.className='m '+cls;d.innerHTML=html;
 if(tools&&tools.length){const t=document.createElement('div');t.className='t';t.textContent='ferramentas: '+tools.join(', ');d.appendChild(t)}
 chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d}
add('b','Oi! Eu sou a <b>Melô</b>, da Empório da Música. Como posso ajudar?');
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const i=document.getElementById('i'),s=document.getElementById('s'),q=i.value.trim();if(!q)return;
 i.value='';add('u',esc(q));s.disabled=true;const w=add('b','…');
 try{const r=await fetch('/chat',{method:'POST',body:JSON.stringify({sessao:sid,mensagem:q})});const j=await r.json();
  w.remove();add('b',fmt(j.resposta||j.erro),j.ferramentas)}catch(x){w.textContent='erro de conexão'}
 s.disabled=false;i.focus()};
</script>"""

_agentes: dict[str, Agente] = {}
_trava = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _enviar(self, codigo: int, corpo: bytes, tipo: str):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        pagina = PAGINA.replace("__HOJE__", config.HOJE.strftime("%d/%m/%Y"))
        self._enviar(200, pagina.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        dados = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        sessao, mensagem = str(dados.get("sessao", ""))[:40], str(dados.get("mensagem", ""))[:2000]
        with _trava:
            agente = _agentes.setdefault(sessao, Agente())
            try:
                saida = {"resposta": agente.responder(mensagem), "ferramentas": agente.ferramentas_da_rodada}
            except Exception as e:  # a UI mostra o erro em vez de travar
                saida = {"erro": f"Erro ao falar com o modelo ({type(e).__name__}). Tente de novo."}
        self._enviar(200, json.dumps(saida, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Melô no ar: http://localhost:{porta}")
    ThreadingHTTPServer(("127.0.0.1", porta), Handler).serve_forever()
