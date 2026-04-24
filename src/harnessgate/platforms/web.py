from __future__ import annotations

import json
import logging
import time
from typing import Any

from aiohttp import web

from ..messages import InboundMessage, OutboundMessage, Sender
from ..platform import (
    ChannelTarget,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformContext,
    SendResult,
)

logger = logging.getLogger("harnessgate.platforms.web")

FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HarnessGate</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
  #header { padding: 16px 24px; border-bottom: 1px solid #222; font-size: 14px; font-weight: 600; color: #888; }
  #messages { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 720px; padding: 12px 16px; border-radius: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
  .msg.user { background: #1a3a5c; align-self: flex-end; }
  .msg.agent { background: #1a1a1a; border: 1px solid #333; }
  .msg.system { color: #666; font-size: 13px; align-self: center; }
  .typing { color: #666; font-style: italic; padding: 8px 16px; }
  #input-area { padding: 16px 24px; border-top: 1px solid #222; display: flex; gap: 12px; }
  #input { flex: 1; padding: 12px 16px; border-radius: 8px; border: 1px solid #333; background: #111; color: #e0e0e0; font-size: 15px; outline: none; }
  #input:focus { border-color: #555; }
  #send { padding: 12px 24px; border-radius: 8px; border: none; background: #2563eb; color: white; font-size: 15px; cursor: pointer; }
  #send:hover { background: #1d4ed8; }
</style>
</head>
<body>
<div id="header">HarnessGate Web UI</div>
<div id="messages"></div>
<div id="input-area">
  <input id="input" type="text" placeholder="Type a message..." autocomplete="off" />
  <button id="send">Send</button>
</div>
<script>
const messages=document.getElementById('messages'),input=document.getElementById('input'),sendBtn=document.getElementById('send');
let eventSource,typing;
const TOKEN=prompt('Enter your user ID or token:')||'anonymous';
function addMsg(t,c){if(typing){typing.remove();typing=null}const d=document.createElement('div');d.className='msg '+c;d.textContent=t;messages.appendChild(d);messages.scrollTop=messages.scrollHeight}
function connect(){eventSource=new EventSource('/stream?token='+encodeURIComponent(TOKEN));eventSource.onopen=()=>addMsg('Connected','system');eventSource.onerror=()=>addMsg('Disconnected. Reconnecting...','system');eventSource.onmessage=e=>{const d=JSON.parse(e.data);if(d.type==='message')addMsg(d.text,'agent');else if(d.type==='typing'){if(!typing){typing=document.createElement('div');typing.className='typing';typing.textContent='Thinking...';messages.appendChild(typing);messages.scrollTop=messages.scrollHeight}}else if(d.type==='connected')addMsg('Session ready ('+d.userId+')','system')}}
function send(){const t=input.value.trim();if(!t)return;fetch('/message',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN},body:JSON.stringify({text:t})});addMsg(t,'user');input.value=''}
sendBtn.onclick=send;input.onkeydown=e=>{if(e.key==='Enter')send()};connect();
</script>
</body>
</html>"""


class WebAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self._sse_clients: dict[str, web.StreamResponse] = {}
        self._on_message: Any = None

    @property
    def id(self) -> str:
        return "web"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            max_text_length=100_000,
            supports_markdown=True,
            supports_typing_indicator=True,
        )

    async def start(self, ctx: PlatformContext) -> None:
        self._on_message = ctx.on_message
        port = int(ctx.config.get("port", 3000))

        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/stream", self._handle_sse)
        app.router.add_post("/message", self._handle_message)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()
        logger.info("Web UI listening on http://localhost:%d", port)

    async def stop(self) -> None:
        for res in self._sse_clients.values():
            await res.write_eof()
        self._sse_clients.clear()
        if self._runner:
            await self._runner.cleanup()

    def _extract_user_id(self, request: web.Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return token or None
        return request.query.get("token") or None

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=FALLBACK_HTML, content_type="text/html")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "clients": len(self._sse_clients)})

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        user_id = self._extract_user_id(request)
        if not user_id:
            return web.json_response({"error": "Missing Authorization or ?token="}, status=401)

        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        await response.prepare(request)

        await response.write(f"data: {json.dumps({'type': 'connected', 'userId': user_id})}\n\n".encode())
        self._sse_clients[user_id] = response
        logger.info("SSE client connected: %s", user_id)

        try:
            async for _ in request.content:
                pass
        except Exception:
            pass
        finally:
            self._sse_clients.pop(user_id, None)
            logger.info("SSE client disconnected: %s", user_id)

        return response

    async def _handle_message(self, request: web.Request) -> web.Response:
        user_id = self._extract_user_id(request)
        if not user_id:
            return web.json_response({"error": "Missing Authorization or ?token="}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        text = body.get("text")
        if not text:
            return web.json_response({"error": "Missing 'text' field"}, status=400)

        msg = InboundMessage(
            id=f"web_{user_id}_{int(time.time() * 1000)}",
            platform="web",
            channel_id=user_id,
            sender=Sender(id=user_id),
            text=text,
            timestamp=time.time(),
            chat_type="direct",
        )
        if self._on_message:
            self._on_message(msg)

        return web.json_response({"ok": True})

    async def send(self, target: ChannelTarget, message: OutboundMessage) -> SendResult:
        client = self._sse_clients.get(target.channel_id)
        if not client:
            return SendResult(success=False, error="Client not connected")
        data = json.dumps({"type": "message", "text": message.text})
        await client.write(f"data: {data}\n\n".encode())
        return SendResult(success=True)

    async def send_typing(self, target: ChannelTarget) -> None:
        client = self._sse_clients.get(target.channel_id)
        if client:
            await client.write(f"data: {json.dumps({'type': 'typing'})}\n\n".encode())
