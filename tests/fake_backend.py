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
    {"name": "alfred", "title": "Alfred", "voice": "en_GB-alan-medium", "greeting": "At your service.",
     "tags": ["technical"], "model": "fake", "temperature": 0.2, "tools": False, "provider": "fake",
     "voice_gender": "male", "voice_pitch": 0.8, "voice_rate": 1.0, "avatar": "🎩",
     "accent_color": "#2c3e50", "builtin": True, "system": "You are Alfred."},
    {"name": "yui", "title": "Yui", "voice": "en_US-amy-medium", "greeting": "Hi hi!",
     "tags": ["office"], "model": "fake", "temperature": 0.7, "tools": False, "provider": "fake",
     "voice_gender": "female", "voice_pitch": 1.35, "voice_rate": 1.15, "avatar": "🌟",
     "accent_color": "#ff6b81", "builtin": True, "system": "You are Yui."},
    {"name": "house", "title": "Dr. House", "voice": "en_US-amy-medium",
     "greeting": "Everybody lies. So, what are you lying about?", "tags": ["medical"], "model": "fake",
     "temperature": 0.6, "tools": False, "provider": "fake", "voice_gender": "male", "voice_pitch": 0.85,
     "voice_rate": 1.05, "avatar": "🩺", "accent_color": "#4a5859", "builtin": True,
     "system": "You are Dr. House."},
]
CHAT_FIELDS = ("name", "title", "temperature", "model", "provider", "tools", "voice", "voice_gender",
               "voice_pitch", "voice_rate", "greeting", "tags", "avatar", "accent_color")
ACCOUNTS = {"ray": "secret"}
SESSIONS = {}      # token -> username
CONVERSATIONS = {}  # "user:persona:session" -> [turns]
PENDING = {}
SEEN = []          # every request body, for assertions


def _chat_view(p):
    return {k: p.get(k) for k in CHAT_FIELDS}


def _user_for(handler):
    tok = handler.headers.get("X-Genesis-Token")
    return SESSIONS.get(tok)


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
        supplied = self.headers.get("X-Genesis-Token")
        if supplied in SESSIONS:
            return True                       # a per-account session token
        if self.token and supplied != self.token:
            self._json(401, {"detail": "missing X-Genesis-Token"})
            return False
        return True

    def do_GET(self):
        path = self.path.split("?")[0]
        qs = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&") if "=" in kv) \
            if "?" in self.path else {}
        from urllib.parse import unquote_plus
        qs = {k: unquote_plus(v) for k, v in qs.items()}
        if path == "/health":
            return self._json(200, {"ok": True, "detail": "ok", "provider": "fake", "model": "fake-model",
                                    "personas": [p["name"] for p in PERSONAS], "chat_auth": bool(self.token),
                                    "admin_auth": bool(self.admin), "client_tools": True})
        if not self._auth(path.startswith("/admin")):
            return
        if path == "/personas":
            return self._json(200, [_chat_view(p) for p in PERSONAS])
        if path == "/admin/personas":
            return self._json(200, PERSONAS)
        if path == "/voice/config":
            return self._json(200, {"stt_engine": "browser", "tts_engine": "browser",
                                    "voices": {p["name"]: {"voice": p["voice"], "gender": p["voice_gender"],
                                                           "pitch": p["voice_pitch"], "rate": p["voice_rate"]}
                                               for p in PERSONAS}})
        if path.startswith("/history/"):
            persona = path.rsplit("/", 1)[1]
            user = _user_for(self) or qs.get("user", "local")
            key = f"{user}:{persona}:{qs.get('session', 'default')}"
            return self._json(200, CONVERSATIONS.get(key, []))
        if path == "/sessions":
            user = _user_for(self) or qs.get("user")
            rows = [{"session": k, "user": k.split(":")[0], "persona": k.split(":")[1], "updated": i}
                    for i, k in enumerate(CONVERSATIONS) if not user or k.startswith(user + ":")]
            return self._json(200, rows)
        if path == "/agent-stats":
            return self._json(200, {"memory": {"used_gb": 5.2, "total_gb": 16.0, "percent": 33},
                                    "gpu": {"used_gb": 3.1, "total_gb": 8.0}})
        if path == "/search":
            return self._json(200, [])
        if path == "/admin/settings":
            return self._json(200, {k: {"value": v, "default": v, "source": "default",
                                        "schema": {"type": type(v).__name__}, "needs_reindex": False}
                                    for k, v in self.settings.items()})
        if path == "/admin/mods":
            return self._json(200, self.mods)
        return self._json(404, {"detail": "no"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if not self._auth(path.startswith("/admin")):
            return
        if path.startswith("/admin/personas/"):
            name = path.rsplit("/", 1)[1]
            p = next((x for x in PERSONAS if x["name"] == name), None)
            if not p:
                return self._json(404, {"detail": f"no persona {name!r}"})
            if p.get("builtin"):
                return self._json(400, {"detail": "builtin personas cannot be deleted"})
            PERSONAS.remove(p)
            return self._json(200, {"name": name, "deleted": True})
        if path.startswith("/sessions/"):
            for k in [k for k in CONVERSATIONS if k.endswith(":" + self.path.split("session=")[-1].split("&")[0])]:
                CONVERSATIONS.pop(k, None)
        self._json(200, {"ok": True})

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        SEEN.append((path, body))
        if path == "/auth/login":
            if ACCOUNTS.get(body.get("username", "").lower()) == body.get("password"):
                tok = f"sess-{body['username'].lower()}"
                SESSIONS[tok] = body["username"].lower()
                return self._json(200, {"token": tok, "username": body["username"].lower()})
            return self._json(401, {"detail": "bad username or password"})
        if path == "/auth/logout":
            SESSIONS.pop(self.headers.get("X-Genesis-Token"), None)
            return self._json(200, {"ok": True})
        if not self._auth(path.startswith("/admin")):
            return
        if path == "/admin/personas":
            if any(p["name"] == body.get("name") for p in PERSONAS):
                return self._json(400, {"detail": "persona exists"})
            p = {"builtin": False, "model": "fake", "provider": "fake", **body}
            p.setdefault("title", p["name"].title())
            PERSONAS.append(p)
            return self._json(200, p)
        if path.startswith("/admin/personas/") and not path.endswith("/mods"):
            name = path.rsplit("/", 1)[1]
            p = next((x for x in PERSONAS if x["name"] == name), None)
            if not p:
                return self._json(404, {"detail": f"no persona {name!r}"})
            if p.get("builtin") and ("system" in body or "title" in body):
                return self._json(400, {"detail": "builtin identity is fixed"})
            p.update(body)
            return self._json(200, p)
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
            if persona not in [p["name"] for p in PERSONAS]:
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

        ev({"type": "start", "persona": persona, "model": "fake-model", "provider": "fake"})
        text = body.get("text", "")
        session = body.get("session", "default")
        user = _user_for(self) or body.get("user", "local")
        convo = CONVERSATIONS.setdefault(f"{user}:{persona}:{session}", [])
        if text:
            convo.append({"role": "user", "content": text, "interrupted": 0})
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
        elif "weather" in text:
            ev({"type": "tool_start", "name": "get_weather", "args": {"place": "here"}})
            ev({"type": "tool", "name": "get_weather", "args": {"place": "here"}, "result": "sunny"})
            reply = "It is sunny here."
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
        if reply:
            convo.append({"role": "assistant", "content": reply, "interrupted": 0})
        ev({"type": "done", "text": reply, "sources": [], "interrupted": False, "pending_tools": [],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19} if reply else None})
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
