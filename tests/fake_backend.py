"""A tiny stand-in for the Genesis API, stdlib only, for tests and smoke
runs. Speaks the same SSE contract, including the client-tools round trip.

Behaviour:
    text containing "disk"     -> tool_call run_command "df -h", then a reply
    text containing "delete"   -> tool_call run_command "rm -rf /tmp/genesis-x"
    text containing "fail"     -> error event
    anything else              -> streams "You said: <text>"
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PERSONAS = [
    {"name": "alfred", "title": "Alfred", "voice": "en_GB-alan-medium", "greeting": "Ready.",
     "tags": ["technical"], "model": "fake", "temperature": 0.2, "tools": False},
    {"name": "yui", "title": "Yui", "voice": "en_US-amy-medium", "greeting": "Hi!",
     "tags": ["office"], "model": "fake", "temperature": 0.7, "tools": False},
]
PENDING = {}
SEEN = []          # every request body, for assertions


class Handler(BaseHTTPRequestHandler):
    token = None
    admin = None
    settings = {"temperature": 0.4, "provider": "ollama", "chat_model": "fake", "tools_enabled": False}
    mods = [{"name": "example", "enabled": False, "loaded": False, "error": None, "doc": "Example mod"}]

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self, admin=False):
        if admin:
            if self.admin and self.headers.get("X-Genesis-Admin") != self.admin:
                self._json(401, {"detail": "missing X-Genesis-Admin"})
                return False
            return True
        if self.token and self.headers.get("X-Genesis-Token") != self.token:
            self._json(401, {"detail": "missing X-Genesis-Token"})
            return False
        return True

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._json(200, {"ok": True, "detail": "ok", "provider": "fake", "model": "fake-model",
                                    "personas": ["alfred", "yui"], "chat_auth": bool(self.token),
                                    "admin_auth": bool(self.admin)})
        if not self._auth(path.startswith("/admin")):
            return
        if path == "/personas":
            return self._json(200, PERSONAS)
        if path == "/voice/config":
            return self._json(200, {"stt_engine": "browser", "tts_engine": "browser",
                                    "voices": {p["name"]: p["voice"] for p in PERSONAS}})
        if path.startswith("/history/"):
            return self._json(200, [])
        if path == "/admin/settings":
            return self._json(200, {k: {"value": v, "default": v, "source": "default",
                                        "schema": {"type": type(v).__name__}, "needs_reindex": False}
                                    for k, v in self.settings.items()})
        if path == "/admin/mods":
            return self._json(200, self.mods)
        return self._json(404, {"detail": "no"})

    def do_DELETE(self):
        if not self._auth():
            return
        self._json(200, {"ok": True})

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        SEEN.append((path, body))
        if not self._auth(path.startswith("/admin")):
            return
        if path.startswith("/admin/settings/"):
            key = path.rsplit("/", 1)[1]
            if key == "temperature" and float(body["value"]) > 2:
                return self._json(400, {"detail": "temperature: above maximum 2.0"})
            self.settings[key] = body["value"]
            return self._json(200, {"key": key, "value": body["value"]})
        if path.startswith("/admin/mods/"):
            _, _, _, name, verb = path.split("/")
            for m in self.mods:
                if m["name"] == name:
                    m["enabled"] = verb == "enable"
            return self._json(200, {"name": name, "enabled": verb == "enable"})
        if path == "/speak":
            return self._json(409, {"detail": "tts_engine is 'browser'"})
        if path.startswith("/chat/"):
            persona = path.rsplit("/", 1)[1]
            if persona not in ("alfred", "yui"):
                return self._json(404, {"detail": f"no persona {persona!r}"})
            return self._chat(persona, body)
        return self._json(404, {"detail": "no"})

    def _chat(self, persona, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def ev(o):
            self.wfile.write(f"data: {json.dumps(o)}\n\n".encode())
            self.wfile.flush()

        ev({"type": "start", "persona": persona, "model": "fake-model"})
        text = body.get("text", "")
        session = body.get("session", "default")
        results = body.get("tool_results")
        tools = {t["function"]["name"] for t in body.get("client_tools") or []}
        if results:
            parked = PENDING.pop(session, None)
            if not parked:
                ev({"type": "error", "message": "no tool call is waiting on this session"})
                ev({"type": "done", "text": "", "sources": [], "interrupted": False, "pending_tools": []})
                self.wfile.write(b"data: [DONE]\n\n")
                return
            for r in results:
                ev({"type": "tool", "name": r["name"], "args": {}, "result": r["result"][:200], "client": True})
            reply = f"The tool said: {results[0]['result'][:60]}"
        elif "fail" in text:
            ev({"type": "error", "message": "model exploded"})
            reply = ""
        elif "disk" in text and "run_command" in tools:
            call = {"id": "call-1", "name": "run_command", "args": {"command": "df -h"}}
            PENDING[session] = call
            ev({"type": "tool_call", **call})
            ev({"type": "done", "text": "", "sources": [], "interrupted": False, "pending_tools": [call]})
            self.wfile.write(b"data: [DONE]\n\n")
            return
        elif "delete" in text and "run_command" in tools:
            call = {"id": "call-2", "name": "run_command", "args": {"command": "rm -rf /tmp/genesis-x"}}
            PENDING[session] = call
            ev({"type": "tool_call", **call})
            ev({"type": "done", "text": "", "sources": [], "interrupted": False, "pending_tools": [call]})
            self.wfile.write(b"data: [DONE]\n\n")
            return
        else:
            ev({"type": "sources", "sources": ["notes.md"]})
            reply = f"You said: {text}. That is all there is to it! Anything else?"
        for word in reply.split(" "):
            ev({"type": "delta", "text": word + " "})
        ev({"type": "done", "text": reply, "sources": [], "interrupted": False, "pending_tools": []})
        self.wfile.write(b"data: [DONE]\n\n")


def start(port=0, token=None, admin=None):
    Handler.token = token
    Handler.admin = admin
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    import sys
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8099)
    print(url, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
