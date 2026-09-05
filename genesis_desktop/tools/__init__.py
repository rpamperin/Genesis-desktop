"""Tools that run on this machine.

The backend's own tools are read-only and sandboxed because the backend may
be on a shared box. This computer is yours, so these go further: a real
shell, files anywhere the user can reach, services, packages, and the
desktop itself. What keeps that safe is the policy in policy.py -- every
call is classified and, unless you have said otherwise, anything that
changes the machine is shown to you first.

A tool is a plain function plus an openai function spec. Local mods add
their own through the same register() call.
"""
from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import config
from . import policy


@dataclass
class Tool:
    name: str
    fn: Callable
    spec: dict
    origin: str = "builtin"
    # "safe": never asks. "mutating": asks under the "ask" policy.
    # "privileged": needs root; always asks unless policy is trusted.
    # None: let policy.classify() look at the arguments.
    risk: Optional[str] = None
    describe: Optional[Callable[[dict], str]] = None   # human summary of a call
    classify: Optional[Callable[[dict], str]] = None   # per-call risk override

    def summary(self, args: dict) -> str:
        if self.describe:
            try:
                return self.describe(args)
            except Exception:
                pass
        return f"{self.name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"


REGISTRY: dict[str, Tool] = {}


def register(spec: dict, fn: Callable = None, *, origin="builtin", risk=None,
             describe=None):
    """register(spec)(fn) as a decorator, or register(spec, fn)."""
    def deco(f):
        name = spec["function"]["name"]
        REGISTRY[name] = Tool(name, f, spec, origin, risk, describe)
        return f
    return deco(fn) if fn else deco


def unregister_origin(origin: str):
    for name in [n for n, t in REGISTRY.items() if t.origin == origin]:
        del REGISTRY[name]


def specs() -> list[dict]:
    if not config.get("local_tools_enabled"):
        return []
    return [t.spec for t in REGISTRY.values()]


def get(name) -> Optional[Tool]:
    return REGISTRY.get(name)


def run(name: str, args: dict) -> str:
    """Execute a tool. Callers decide whether to ask the user first
    (policy.decide); this only runs it."""
    t = REGISTRY.get(name)
    if not t:
        return f"no such local tool: {name}"
    try:
        sig = inspect.signature(t.fn)
        known = {k: v for k, v in args.items() if k in sig.parameters} \
            if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()) \
            else args
        out = t.fn(**known)
        return "" if out is None else str(out)
    except TypeError as e:
        return f"bad arguments for {name}: {e}"
    except Exception as e:
        return f"{name} failed: {e}\n{traceback.format_exc(limit=2)}"


def load_builtins():
    from . import desktop, system  # noqa: F401  (registers on import)
    return REGISTRY
