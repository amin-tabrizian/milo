"""Claude Code hook (PreToolUse, Bash) in Milo's Claude profile: refuses a command that would kill the Milo bridge,
goose or Claude itself. Milo runs inside them, so it would end mid-reply and the app would stay down (2026-10-19).
Milo restarts the bridge with <restart/> instead. server.py installs this hook; it runs in every permission mode."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

KILL_WORD = re.compile(r"\b(p?kill|killall)\b")
REFUSAL = ("Blocked: this would stop the Milo server you are running in. You would end mid-reply and the user "
           "would lose the app. To restart the server, add <restart/> to your reply instead: the app restarts "
           "itself after your reply and is back in about 20 seconds.")


def ps(fields: str, pids: list[int]) -> dict[int, str]:
    out = subprocess.run(["ps", "-o", f"pid=,{fields}=", "-p", ",".join(map(str, pids))],
                         capture_output=True, text=True).stdout
    return {int(pid): rest.strip() for pid, _, rest in (line.strip().partition(" ") for line in out.splitlines())}


def milo_processes() -> tuple[list[tuple[int, str, str]], list[str]]:
    """This hook's parents up to the bridge (Claude, claude-agent-acp, goose, server.py and the uv that started it),
    and words that name them in a pid lookup."""
    tree = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    parent = dict(tuple(map(int, line.split())) for line in tree.splitlines() if line.strip())
    chain, pid = [], parent.get(os.getpid(), 1)
    while pid > 1 and pid not in chain:
        chain.append(pid)
        pid = parent.get(pid, 1)
    names, lines = ps("comm", chain), ps("args", chain)
    procs = [(p, Path(names.get(p, "")).name, lines.get(p, "")) for p in chain]
    bridge = next((i for i, (_, _, line) in enumerate(procs) if "server.py" in line), None)
    if bridge is not None:   # not the shell or Terminal that started it
        procs = procs[:bridge + 2] if bridge + 1 < len(procs) and procs[bridge + 1][1] == "uv" else procs[:bridge + 1]
    markers = ["server.py", "goose", "claude-agent-acp"]
    if bridge is not None:
        listen = subprocess.run(["lsof", "-a", "-p", str(procs[bridge][0]), "-iTCP", "-sTCP:LISTEN", "-P", "-n", "-Fn"],
                                capture_output=True, text=True).stdout
        markers += [f":{m}" for m in re.findall(r"^n.*:(\d+)$", listen, re.M)]
    return procs, markers


def main() -> int:
    command = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
    if not KILL_WORD.search(command):   # most commands: no need to load the parser
        return 0
    sys.path.insert(0, str(Path(__file__).parent))
    from permissions import stops_milo
    if stops_milo(command, *milo_processes()):
        print(REFUSAL, file=sys.stderr)
        return 2   # Claude Code drops the command and shows Claude the reason
    return 0


if __name__ == "__main__":
    sys.exit(main())
