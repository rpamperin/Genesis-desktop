"""System tools: shell, files, services, packages, processes, logs.

Everything mutating goes through the policy before it gets here. Root work
uses pkexec, so the desktop shows its own password prompt -- this program
never sees or stores the password.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .. import config
from . import register


def _wd() -> Path:
    return config.work_dir()


def _path(p: str) -> Path:
    q = Path(os.path.expanduser(os.path.expandvars(p or ".")))
    return q if q.is_absolute() else _wd() / q


def _run(argv, timeout=None, input_text=None, cwd=None, shell=False):
    try:
        r = subprocess.run(
            argv, shell=shell, capture_output=True, text=True,
            timeout=timeout or config.get("tool_timeout"), input=input_text,
            cwd=cwd or str(_wd()),
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout or config.get('tool_timeout')}s"
    except FileNotFoundError as e:
        return f"not installed: {e.filename}"
    out = (r.stdout or "") + (r.stderr or "")
    out = out.strip()
    if len(out) > 12000:
        out = out[:6000] + f"\n... [{len(out) - 12000} chars cut] ...\n" + out[-6000:]
    return out or f"(exit {r.returncode}, no output)"


def _as_root(argv):
    if os.geteuid() == 0:
        return argv
    if shutil.which("pkexec"):
        return ["pkexec", "env", f"DISPLAY={os.getenv('DISPLAY', '')}",
                f"XAUTHORITY={os.getenv('XAUTHORITY', '')}"] + argv
    if shutil.which("sudo"):
        return ["sudo", "-n"] + argv      # non-interactive; fails loudly if no cached creds
    return argv


# ----------------------------------------------------------------------
# shell
# ----------------------------------------------------------------------
@register({
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run a shell command on the user's desktop computer (bash -c). "
            "Pipes and redirects work. Read-only commands run at once; "
            "commands that change the machine are shown to the user for "
            "approval first. Set as_root=true for things that need root; the "
            "desktop will show a password prompt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "the command line"},
                "as_root": {"type": "boolean", "description": "run via pkexec as root"},
                "cwd": {"type": "string", "description": "working directory"},
                "timeout": {"type": "integer", "description": "seconds, default 60"},
            },
            "required": ["command"],
        },
    },
}, describe=lambda a: ("# " if a.get("as_root") else "$ ") + str(a.get("command", "")))
def run_command(command: str, as_root: bool = False, cwd: str = None,
                timeout: int = None):
    argv = ["bash", "-lc", command]
    if as_root:
        argv = _as_root(argv)
    return _run(argv, timeout=timeout, cwd=str(_path(cwd)) if cwd else None)


# ----------------------------------------------------------------------
# files
# ----------------------------------------------------------------------
@register({
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file anywhere the user can read. Paths may be relative to the home directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer", "description": "default 12000"},
            },
            "required": ["path"],
        },
    },
}, risk="safe", describe=lambda a: f"read {a.get('path')}")
def read_file(path: str, max_chars: int = 12000):
    p = _path(path)
    if not p.exists():
        return f"no such file: {p}"
    if p.is_dir():
        return list_directory(str(p))
    try:
        data = p.read_bytes()
    except PermissionError:
        return f"permission denied: {p} (try run_command with as_root)"
    if b"\x00" in data[:4096]:
        return f"{p} is binary ({len(data)} bytes)"
    text = data.decode("utf-8", "replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... [{len(text) - max_chars} more chars]"
    return text


@register({
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write (create or overwrite) a text file. A backup copy (.bak) is kept when overwriting.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
    },
}, risk="mutating", describe=lambda a: f"write {len(str(a.get('content', '')))} chars to {a.get('path')}")
def write_file(path: str, content: str, append: bool = False):
    p = _path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not append:
            shutil.copy2(p, p.with_name(p.name + ".bak"))
        with open(p, "a" if append else "w") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {p}"
    except PermissionError:
        return f"permission denied: {p} (use run_command with as_root and tee)"


@register({
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "List a directory with sizes and modification times.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "show_hidden": {"type": "boolean"}},
        },
    },
}, risk="safe", describe=lambda a: f"list {a.get('path') or '~'}")
def list_directory(path: str = "", show_hidden: bool = False):
    p = _path(path)
    if not p.is_dir():
        return f"not a directory: {p}"
    import datetime
    rows = []
    try:
        for x in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if x.name.startswith(".") and not show_hidden:
                continue
            try:
                st = x.stat()
                ts = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                size = "<dir>" if x.is_dir() else _human(st.st_size)
            except OSError:
                ts, size = "?", "?"
            rows.append(f"{size:>8}  {ts}  {x.name}{'/' if x.is_dir() else ''}")
    except PermissionError:
        return f"permission denied: {p}"
    return f"{p}\n" + ("\n".join(rows) or "(empty)")


def _human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}P"


@register({
    "type": "function",
    "function": {
        "name": "search_files",
        "description": "Find files by name pattern (glob) under a directory, or grep text inside files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string", "description": "glob such as *.log"},
                "text": {"type": "string", "description": "text to grep for"},
                "max_results": {"type": "integer"},
            },
        },
    },
}, risk="safe", describe=lambda a: f"search {a.get('path') or '~'} for {a.get('name') or a.get('text')}")
def search_files(path: str = "", name: str = None, text: str = None,
                 max_results: int = 200):
    p = _path(path)
    if text:
        argv = ["grep", "-rIl", "--exclude-dir=.git", "--exclude-dir=node_modules",
                "--exclude-dir=.venv", "-m", "1", text, str(p)]
        if name:
            argv.insert(1, f"--include={name}")
        return _run(argv)
    argv = ["find", str(p), "-xdev", "-name", name or "*", "-not", "-path",
            "*/.git/*", "-not", "-path", "*/node_modules/*"]
    out = _run(argv)
    lines = out.splitlines()
    if len(lines) > max_results:
        return "\n".join(lines[:max_results]) + f"\n... {len(lines) - max_results} more"
    return out


# ----------------------------------------------------------------------
# system
# ----------------------------------------------------------------------
@register({
    "type": "function",
    "function": {
        "name": "system_info",
        "description": "Overview of this computer: OS, kernel, CPU, memory, disk, uptime, GPU, network.",
        "parameters": {"type": "object", "properties": {}},
    },
}, risk="safe", describe=lambda a: "system overview")
def system_info():
    parts = [
        f"host: {platform.node()}  user: {os.getenv('USER', '?')}",
        f"os: {_os_name()}  kernel: {platform.release()}  arch: {platform.machine()}",
        f"desktop: {os.getenv('XDG_CURRENT_DESKTOP', '?')} ({os.getenv('XDG_SESSION_TYPE', '?')})",
        "uptime: " + _run(["uptime", "-p"]),
        "cpu: " + _run(["bash", "-c", "nproc; lscpu | grep 'Model name' | sed 's/.*: *//'"]).replace("\n", " cores, "),
        "memory:\n" + _run(["free", "-h"]),
        "disk:\n" + _run(["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay"]),
    ]
    if shutil.which("nvidia-smi"):
        parts.append("gpu:\n" + _run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                        "--format=csv,noheader"]))
    if shutil.which("ip"):
        parts.append("network:\n" + _run(["ip", "-br", "addr"]))
    return "\n".join(parts)


def _os_name():
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.system()


@register({
    "type": "function",
    "function": {
        "name": "processes",
        "description": "Top processes by CPU or memory, or search for a process by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by": {"type": "string", "enum": ["cpu", "mem"]},
                "name": {"type": "string", "description": "filter by name"},
                "limit": {"type": "integer"},
            },
        },
    },
}, risk="safe", describe=lambda a: f"processes ({a.get('name') or a.get('sort_by', 'cpu')})")
def processes(sort_by: str = "cpu", name: str = None, limit: int = 15):
    key = "-%mem" if sort_by == "mem" else "-%cpu"
    out = _run(["ps", "-eo", "pid,user,%cpu,%mem,etime,comm,args", "--sort", key])
    lines = out.splitlines()
    if name:
        lines = [lines[0]] + [ln for ln in lines[1:] if name.lower() in ln.lower()]
    return "\n".join(lines[: limit + 1])


@register({
    "type": "function",
    "function": {
        "name": "service",
        "description": "Inspect or control a systemd service. status/logs are read-only; start/stop/restart/enable/disable need root.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {"type": "string",
                           "enum": ["status", "logs", "start", "stop", "restart",
                                    "enable", "disable", "list-failed"]},
                "user": {"type": "boolean", "description": "a --user service"},
                "lines": {"type": "integer", "description": "log lines, default 50"},
            },
            "required": ["action"],
        },
    },
}, describe=lambda a: f"systemctl {a.get('action')} {a.get('name', '')}")
def service(action: str, name: str = "", user: bool = False, lines: int = 50):
    scope = ["--user"] if user else []
    if action == "list-failed":
        return _run(["systemctl"] + scope + ["--failed", "--no-pager"])
    if not name:
        return "name is required"
    if action == "status":
        return _run(["systemctl"] + scope + ["status", "--no-pager", "-l", name])
    if action == "logs":
        return _run(["journalctl"] + scope + ["-u", name, "-n", str(lines),
                                              "--no-pager"])
    argv = ["systemctl"] + scope + [action, name]
    if not user:
        argv = _as_root(argv)
    out = _run(argv)
    return out + "\n" + _run(["systemctl"] + scope + ["is-active", name])


# service risk depends on the action; a describe-only tool gets risk=None and
# policy falls back to "mutating", so refine it here
def _service_risk(args):
    a = args.get("action")
    if a in ("status", "logs", "list-failed"):
        return "safe"
    return "mutating" if args.get("user") else "privileged"


from . import REGISTRY as _R  # noqa: E402
_R["service"].risk = None
_R["service"].classify = _service_risk


@register({
    "type": "function",
    "function": {
        "name": "packages",
        "description": "Search, inspect, install, remove or update packages with apt. install/remove/upgrade need root.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["search", "info", "installed", "install", "remove",
                                    "update", "upgrade", "list-upgradable"]},
                "name": {"type": "string"},
            },
            "required": ["action"],
        },
    },
}, describe=lambda a: f"apt {a.get('action')} {a.get('name', '')}")
def packages(action: str, name: str = ""):
    if action == "search":
        return _run(["apt-cache", "search", "--names-only", name])
    if action == "info":
        return _run(["apt-cache", "show", name])
    if action == "installed":
        return _run(["bash", "-c", f"dpkg -l | grep -i {name!r} || echo 'not installed'"])
    if action == "list-upgradable":
        return _run(["apt", "list", "--upgradable"])
    env = ["env", "DEBIAN_FRONTEND=noninteractive"]
    if action == "update":
        return _run(_as_root(["apt-get", "update"]), timeout=300)
    if action == "upgrade":
        return _run(_as_root(env + ["apt-get", "-y", "upgrade"]), timeout=1800)
    if action == "install":
        return _run(_as_root(env + ["apt-get", "-y", "install"] + name.split()), timeout=1800)
    if action == "remove":
        return _run(_as_root(env + ["apt-get", "-y", "remove"] + name.split()), timeout=600)
    return f"unknown action {action}"


_R["packages"].classify = lambda a: "safe" if a.get("action") in (
    "search", "info", "installed", "list-upgradable") else "privileged"


@register({
    "type": "function",
    "function": {
        "name": "system_logs",
        "description": "Recent system log lines (journalctl), optionally errors only or for the current boot.",
        "parameters": {
            "type": "object",
            "properties": {
                "lines": {"type": "integer"},
                "errors_only": {"type": "boolean"},
                "this_boot": {"type": "boolean"},
                "grep": {"type": "string"},
            },
        },
    },
}, risk="safe", describe=lambda a: "system logs")
def system_logs(lines: int = 80, errors_only: bool = False,
                this_boot: bool = True, grep: str = None):
    argv = ["journalctl", "--no-pager", "-n", str(lines)]
    if this_boot:
        argv.append("-b")
    if errors_only:
        argv += ["-p", "err"]
    if grep:
        argv += ["-g", grep]
    return _run(argv)
