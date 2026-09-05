"""Who decides whether a tool call runs.

Three policies, chosen in Settings > Local tools:

    safe     read-only calls run; anything that changes the machine is refused
    ask      read-only calls run; changes are shown to you to allow or deny
    trusted  everything runs, privileged calls still go through pkexec

Classification looks at the tool's declared risk, or for the shell at the
command itself. A remembered "always allow" is matched on the exact
command line, nothing looser -- "rm" is not a thing to trust by prefix.
"""
from __future__ import annotations

import shlex

from .. import config

READ_ONLY_CMDS = {
    "ls", "cat", "head", "tail", "less", "wc", "grep", "rg", "find", "stat",
    "file", "df", "du", "free", "uptime", "date", "whoami", "id", "hostname",
    "uname", "which", "type", "ps", "top", "htop", "nvidia-smi", "lsblk",
    "lscpu", "lsusb", "lspci", "lsmod", "ip", "ss", "ping", "dig", "nslookup",
    "env", "printenv", "echo", "pwd", "true", "false", "tree", "md5sum",
    "sha256sum", "sort", "uniq", "cut", "awk", "sed", "diff", "cmp", "xdg-mime",
    "lsb_release", "dpkg", "apt-cache", "apt", "snap", "flatpak", "pip",
    "python3", "python", "git", "systemctl", "journalctl", "dmesg", "nproc",
    "sensors", "xrandr", "pactl", "amixer", "nmcli", "ufw", "ss", "netstat",
    "mount", "findmnt", "blkid", "getent", "locale", "timedatectl", "loginctl",
    "hostnamectl", "gsettings", "dconf", "xdg-settings", "ollama", "curl", "wget",
}
# subcommands that make an otherwise read-only program mutate
MUTATING_SUB = {
    "systemctl": {"start", "stop", "restart", "reload", "enable", "disable",
                  "mask", "unmask", "daemon-reload", "kill", "edit", "set-property"},
    "apt": {"install", "remove", "purge", "upgrade", "full-upgrade",
            "dist-upgrade", "autoremove", "update", "clean", "autoclean"},
    "apt-get": {"install", "remove", "purge", "upgrade", "dist-upgrade",
                "autoremove", "update", "clean"},
    "snap": {"install", "remove", "refresh", "revert", "enable", "disable",
             "set", "connect", "disconnect"},
    "flatpak": {"install", "uninstall", "update", "override", "remove"},
    "pip": {"install", "uninstall"},
    "git": {"push", "reset", "checkout", "clean", "rebase", "merge", "commit",
            "rm", "mv", "stash", "branch", "tag"},
    "ollama": {"pull", "rm", "create", "push", "cp"},
    "nmcli": {"connection", "con", "c", "device", "dev", "d", "radio", "r", "networking"},
    "ufw": {"enable", "disable", "allow", "deny", "delete", "reset", "default", "reject", "limit"},
    "gsettings": {"set", "reset", "reset-recursively"},
    "dconf": {"write", "reset", "load"},
    "xdg-settings": {"set"},
    "pactl": {"set-sink-volume", "set-sink-mute", "set-source-volume",
              "set-source-mute", "set-default-sink", "set-default-source",
              "load-module", "unload-module"},
    "amixer": {"set", "sset"},
    "curl": {"-o", "-O", "--output", "-d", "--data", "-X", "-T", "--upload-file"},
    "wget": {"-O", "-o", "--output-document"},
    "sed": {"-i", "--in-place"},
    "timedatectl": {"set-time", "set-timezone", "set-ntp", "set-local-rtc"},
    "hostnamectl": {"set-hostname", "hostname"},
    "loginctl": {"terminate-session", "kill-session", "lock-session", "unlock-session"},
    "mount": {"-o", "-t", "/"},        # bare `mount` lists; with args it mounts
    "python3": {"-c", "-m"},
    "python": {"-c", "-m"},
    "ip": {"link", "addr", "route", "neigh"},   # `ip link set` etc; `ip a` is fine
}
IP_READ = {"a", "addr", "address", "link", "route", "r", "neigh", "n", "-s", "-br", "-c", "-4", "-6"}

PRIVILEGED_CMDS = {"sudo", "pkexec", "su", "doas"}
DANGEROUS_CMDS = {"rm", "rmdir", "dd", "mkfs", "mkfs.ext4", "mkfs.vfat", "fdisk",
                  "parted", "sfdisk", "wipefs", "shred", "chmod", "chown", "chgrp",
                  "kill", "pkill", "killall", "reboot", "shutdown", "poweroff",
                  "halt", "init", "telinit", "mv", "cp", "ln", "truncate", "tee",
                  "crontab", "useradd", "userdel", "usermod", "passwd", "chpasswd",
                  "visudo", "iptables", "nft", "modprobe", "rmmod", "insmod",
                  "swapoff", "swapon", "umount", "mkswap", "xdotool", "dpkg",
                  "update-alternatives", "update-grub", "grub-install"}
SHELL_META = set("|&;><`$()")


def classify_command(command: str) -> str:
    """'safe' | 'mutating' | 'privileged' for a shell command line."""
    if not command.strip():
        return "safe"
    worst = "safe"
    # redirects and substitutions can write files or run anything
    if ">" in command or "$(" in command or "`" in command:
        worst = "mutating"
    for stage in _split_stages(command):
        worst = _worse(worst, _classify_simple(stage))
    return worst


def _classify_simple(stage: str) -> str:
    """One pipeline stage, no operators inside."""
    try:
        parts = shlex.split(stage)
    except ValueError:
        return "mutating"
    if not parts:
        return "safe"
    # leading VAR=value assignments
    while parts and "=" in parts[0] and not parts[0].startswith("-"):
        parts = parts[1:]
    if not parts:
        return "safe"
    exe = parts[0].rsplit("/", 1)[-1]
    if exe in PRIVILEGED_CMDS:
        return "privileged"
    if exe in DANGEROUS_CMDS:
        return "mutating"
    if exe == "ip":
        rest = [p for p in parts[1:] if not p.startswith("-")]
        if rest and rest[0] in ("link", "addr", "address", "route", "neigh") and \
           len(rest) > 1 and rest[1] not in ("show", "list", "ls", "get"):
            return "mutating"
        return "safe"
    if exe in READ_ONLY_CMDS:
        subs = MUTATING_SUB.get(exe)
        if subs and any(p in subs for p in parts[1:]):
            return "mutating"
        if exe == "mount" and len(parts) > 1:
            return "mutating"
        return "safe"
    return "mutating"          # unknown program: assume it does something


def _split_stages(command: str):
    out, cur, quote = [], [], None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "|;&":
            if cur:
                out.append("".join(cur).strip())
            cur = []
            if i + 1 < len(command) and command[i + 1] == ch:
                i += 1
        else:
            cur.append(ch)
        i += 1
    if cur:
        out.append("".join(cur).strip())
    return [s for s in out if s]


def _worse(a, b):
    order = {"safe": 0, "mutating": 1, "privileged": 2}
    return a if order[a] >= order[b] else b


def classify(tool, args: dict) -> str:
    """Risk of one call, using the tool's declared risk or the arguments."""
    if getattr(tool, "classify", None):
        try:
            return tool.classify(args) or "mutating"
        except Exception:
            return "mutating"
    if tool.risk:
        return tool.risk
    if tool.name == "run_command":
        cmd = str(args.get("command", ""))
        risk = classify_command(cmd)
        if args.get("as_root"):
            risk = "privileged"
        return risk
    return "mutating"


def decide(tool, args: dict) -> str:
    """'run' | 'ask' | 'refuse'  -- the answer before the user is consulted."""
    risk = classify(tool, args)
    pol = config.get("tool_policy")
    if risk == "privileged" and not config.get("allow_privileged"):
        return "refuse"
    if risk == "safe":
        return "run"
    if pol == "safe":
        return "refuse"
    if pol == "trusted":
        return "run"
    if tool.name == "run_command" and \
            str(args.get("command", "")).strip() in config.get("tool_always_allow"):
        return "run"
    return "ask"


def remember_allow(tool, args: dict):
    if tool.name != "run_command":
        return
    cmd = str(args.get("command", "")).strip()
    cur = list(config.get("tool_always_allow"))
    if cmd and cmd not in cur:
        cur.append(cmd)
        config.set("tool_always_allow", cur)
