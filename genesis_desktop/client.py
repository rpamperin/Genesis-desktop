"""HTTP client for the Genesis backend.

Blocking, on purpose: every call here is made from a worker thread, never
from the UI thread. The streaming turn is a generator of event dicts, the
same events engine.Session.turn() yields on the backend, so the desktop and
the CLI consume the identical contract.
"""
import json
import threading
from typing import Iterator, Optional

import httpx

from . import config


class BackendError(Exception):
    pass


class GenesisClient:
    def __init__(self, base_url=None, api_token=None, admin_token=None):
        self._base = base_url
        self._api = api_token
        self._admin = admin_token
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    @property
    def base_url(self):
        return (self._base or config.get("backend_url")).rstrip("/")

    def _headers(self, admin=False, chat=False):
        """Chat calls carry the admin token too when we have one: the
        backend accepts it optionally there (maybe_admin) to unlock
        admin-gated tools such as Yui's self-admin mod."""
        h = {}
        acct = config.get("account_token")
        tok = self._api if self._api is not None else config.get("api_token")
        if acct:
            h["X-Genesis-Token"] = acct
        elif tok:
            h["X-Genesis-Token"] = tok
        if admin or chat:
            adm = self._admin if self._admin is not None else config.get("admin_token")
            if adm:
                h["X-Genesis-Admin"] = adm
        return h

    @staticmethod
    def supports_client_tools(health: dict):
        """True / False when the backend says, None when it predates the
        client-tools protocol (and will silently ignore client_tools)."""
        if not isinstance(health, dict) or "client_tools" not in health:
            return None
        return bool(health.get("client_tools"))

    def _client(self, timeout=None):
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout or httpx.Timeout(config.get("connect_timeout"), read=30.0),
        )

    def _req(self, method, path, admin=False, timeout=None, chat=False, **kw):
        try:
            with self._client(timeout) as c:
                r = c.request(method, path, headers=self._headers(admin, chat), **kw)
        except httpx.HTTPError as e:
            raise BackendError(f"cannot reach {self.base_url}: {e}") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise BackendError(f"{method} {path}: {r.status_code} {detail}")
        if not r.content:
            return None
        return r.json()

    # ------------------------------------------------------------------
    # plain calls
    # ------------------------------------------------------------------
    def health(self):
        return self._req("GET", "/health")

    def personas(self):
        return self._req("GET", "/personas")

    def voice_config(self):
        return self._req("GET", "/voice/config")

    # ------------------------------------------------------------------
    # accounts (backends with per-account logins)
    # ------------------------------------------------------------------
    def login(self, username, password):
        """-> (token, username). No token needed for this call."""
        try:
            with self._client() as c:
                r = c.post("/auth/login", json={"username": username, "password": password})
        except httpx.HTTPError as e:
            raise BackendError(f"cannot reach {self.base_url}: {e}") from e
        if r.status_code == 404:
            raise BackendError("this backend has no account logins (older version)")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise BackendError(f"login: {detail}")
        d = r.json()
        return d["token"], d.get("username", username)

    def logout(self):
        tok = config.get("account_token")
        if not tok:
            return
        try:
            with self._client() as c:
                c.post("/auth/logout", headers={"X-Genesis-Token": tok})
        except httpx.HTTPError:
            pass

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    def sessions(self, persona=None):
        """[{session, user, persona, created, updated}] newest first."""
        rows = self._req("GET", "/sessions", params={"user": config.get("user")}) or []
        out = []
        for r in rows:
            key = r.get("session", "")
            parts = key.split(":")
            # store keys are user:persona:session
            name = parts[2] if len(parts) >= 3 else key
            p = r.get("persona") or (parts[1] if len(parts) >= 3 else "")
            if persona and p != persona:
                continue
            out.append({"name": name, "persona": p, "updated": r.get("updated"), "key": key})
        return out

    def delete_session(self, persona, name):
        return self._req("DELETE", f"/sessions/{persona}", params={
            "session": name, "user": config.get("user")})

    def search(self, q, persona=None, limit=50):
        params = {"q": q, "user": config.get("user"), "limit": limit}
        if persona:
            params["persona"] = persona
        return self._req("GET", "/search", params=params)

    def agent_stats(self):
        return self._req("GET", "/agent-stats")

    def history(self, persona, limit=100):
        return self._req("GET", f"/history/{persona}", params={
            "session": config.get("session"), "user": config.get("user"),
            "limit": limit,
        })

    def clear_history(self, persona):
        return self._req("DELETE", f"/history/{persona}", params={
            "session": config.get("session"), "user": config.get("user"),
        })

    def ask(self, persona, text, rag=None):
        return self._req("POST", f"/ask/{persona}", json={
            "text": text, "session": config.get("session"),
            "user": config.get("user"), "rag": rag,
        }, timeout=httpx.Timeout(config.get("connect_timeout"), read=300.0))

    def speak(self, text, persona) -> bytes:
        """Backend piper. Returns wav bytes."""
        try:
            with self._client(httpx.Timeout(config.get("connect_timeout"), read=90.0)) as c:
                r = c.post("/speak", headers=self._headers(),
                           json={"text": text, "persona": persona})
        except httpx.HTTPError as e:
            raise BackendError(str(e)) from e
        if r.status_code >= 400:
            raise BackendError(f"speak: {r.status_code} {r.text[:200]}")
        return r.content

    def transcribe(self, wav_bytes: bytes) -> str:
        try:
            with self._client(httpx.Timeout(config.get("connect_timeout"), read=120.0)) as c:
                r = c.post("/transcribe", headers=self._headers(),
                           files={"audio": ("clip.wav", wav_bytes, "audio/wav")})
        except httpx.HTTPError as e:
            raise BackendError(str(e)) from e
        if r.status_code >= 400:
            raise BackendError(f"transcribe: {r.status_code} {r.text[:200]}")
        return r.json().get("text", "")

    # ------------------------------------------------------------------
    # admin
    # ------------------------------------------------------------------
    def admin_settings(self):
        return self._req("GET", "/admin/settings", admin=True)

    def admin_set(self, key, value):
        return self._req("POST", f"/admin/settings/{key}", admin=True,
                         json={"value": value})

    def admin_reset(self, key):
        return self._req("DELETE", f"/admin/settings/{key}", admin=True)

    def admin_mods(self):
        return self._req("GET", "/admin/mods", admin=True)

    def admin_mod_enable(self, name, enabled=True):
        verb = "enable" if enabled else "disable"
        return self._req("POST", f"/admin/mods/{name}/{verb}", admin=True)

    def admin_models(self):
        return self._req("GET", "/admin/models", admin=True)

    def admin_providers(self):
        return self._req("GET", "/admin/providers", admin=True)

    def admin_diagnostics(self):
        return self._req("GET", "/admin/diagnostics", admin=True)

    def admin_personas(self):
        return self._req("GET", "/admin/personas", admin=True)

    def admin_persona_create(self, data: dict):
        return self._req("POST", "/admin/personas", admin=True, json=data)

    def admin_persona_update(self, name, data: dict):
        return self._req("POST", f"/admin/personas/{name}", admin=True, json=data)

    def admin_persona_delete(self, name):
        return self._req("DELETE", f"/admin/personas/{name}", admin=True)

    def admin_accounts(self):
        return self._req("GET", "/admin/accounts", admin=True)

    def admin_account_create(self, username, password):
        return self._req("POST", "/admin/accounts", admin=True,
                         json={"username": username, "password": password})

    def admin_reindex(self, persona=None, wipe=False):
        params = {"wipe": wipe}
        if persona:
            params["persona"] = persona
        return self._req("POST", "/admin/reindex", admin=True, params=params,
                         timeout=httpx.Timeout(5, read=600.0))

    # ------------------------------------------------------------------
    # streaming turns
    # ------------------------------------------------------------------
    def cancel(self):
        """Abort the in-flight stream. The backend keeps the partial reply
        and marks it interrupted, so the model knows it was cut off."""
        self._cancel.set()

    def turn(self, persona, text="", client_tools=None, tool_results=None,
             rag=None, voice=True) -> Iterator[dict]:
        """Yield engine events for one turn. See genesis/core/engine.py."""
        self._cancel.clear()
        body = {
            "text": text, "session": config.get("session"),
            "user": config.get("user"), "rag": rag, "voice": voice,
        }
        if client_tools:
            body["client_tools"] = client_tools
        if tool_results:
            body["tool_results"] = tool_results
        timeout = httpx.Timeout(config.get("connect_timeout"), read=600.0)
        try:
            with self._client(timeout) as c:
                with c.stream("POST", f"/chat/{persona}", json=body,
                              headers=self._headers(chat=True)) as r:
                    if r.status_code >= 400:
                        r.read()
                        try:
                            detail = r.json().get("detail", r.text)
                        except ValueError:
                            detail = r.text
                        yield {"type": "error", "message": f"{r.status_code} {detail}"}
                        yield {"type": "done", "text": "", "sources": [],
                               "interrupted": False, "pending_tools": [],
                               "failed": True}
                        return
                    for ev in parse_sse(r.iter_lines(), self._cancel):
                        yield ev
                        if ev.get("type") == "done":
                            return
        except httpx.HTTPError as e:
            if self._cancel.is_set():
                yield {"type": "done", "text": "", "sources": [],
                       "interrupted": True, "pending_tools": [], "cancelled": True}
                return
            yield {"type": "error", "message": f"connection failed: {e}"}
            yield {"type": "done", "text": "", "sources": [],
                   "interrupted": False, "pending_tools": [], "failed": True}
        if self._cancel.is_set():
            yield {"type": "done", "text": "", "sources": [],
                   "interrupted": True, "pending_tools": [], "cancelled": True}


def parse_sse(lines, cancel: Optional[threading.Event] = None) -> Iterator[dict]:
    """Turn `data:` lines into event dicts. Stops on [DONE] or cancel."""
    for line in lines:
        if cancel is not None and cancel.is_set():
            return
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue
