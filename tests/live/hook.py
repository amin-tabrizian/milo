"""PreToolUse hook for the live behavior suite: logs every tool call Milo's Claude makes and blocks anything that could
reach the user's real things. It runs from the sandbox's project settings (<sandbox>/work/.claude/settings.json).

  hook.py --root <sandbox> --log <calls.jsonl>

Policy (fail closed): reads pass; writes pass only inside the sandbox or a temp folder; milo-google, milo-weather and
milo-planner pass
because the eval bridge fakes them in-process; claude.ai connectors, sub-agents, crons and anything unknown are blocked and logged.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

READ_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch", "TodoWrite", "ToolSearch",
              "BashOutput", "ListMcpResourcesTool", "ReadMcpResourceTool", "ExitPlanMode", "Skill"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# shell words that act on the Mac or the outside world, whatever the paths
HARD_DENY = re.compile(r"\b(kill|pkill|killall|launchctl|osascript|shutdown|reboot|sudo|ssh|scp|sendmail|smtplib|"
                       r"crontab|security\s+(add|delete|set)|git\s+(push|commit|reset|checkout|clean))\b|"
                       r"(\A|[;&|(\n])\s*open\s+|requests\.(post|put|patch|delete)|httpx\.(post|put|patch|delete)|"
                       r"\bgh\s+\S+\s+(create|comment|close|merge|edit|delete)\b|"
                       r"(python\S*|uv\s+run|nohup)[^;&|\n]*\b(server|restart)\.py")
# paths outside the sandbox that a writing command must not name (reads of them are fine)
REAL_PATH = re.compile(r"/Users/|~|\$HOME|\$\{HOME\}|expanduser|Path\.home|getenv\(['\"]HOME|environ\[['\"]HOME")


def allowed_roots(root: Path) -> list[Path]:
    roots = [root, Path("/tmp"), Path(tempfile.gettempdir())]
    return [Path(os.path.realpath(r)) for r in roots]


def inside(path: str, roots: list[Path], cwd: str) -> bool:
    p = Path(os.path.expanduser(path))
    p = Path(os.path.realpath(p if p.is_absolute() else Path(cwd) / p))
    return any(p == r or r in p.parents for r in roots)


def shell_reads(command: str) -> bool:
    try:
        from permissions import classify
        return bool(classify("", {"command": command}).get("read_only"))
    except Exception:
        return False


def decide(tool: str, args: dict, root: Path, cwd: str) -> tuple[str, str]:
    """('allow' | 'deny', reason)."""
    roots = allowed_roots(root)
    if tool in READ_TOOLS:
        return "allow", "read"
    if tool in WRITE_TOOLS:
        path = args.get("file_path") or args.get("notebook_path") or ""
        if path and inside(path, roots, cwd):
            return "allow", "write in sandbox"
        return "deny", f"Blocked: {path or 'that file'} is outside this test's files."
    if tool == "Bash":
        cmd = str(args.get("command") or "")
        if HARD_DENY.search(cmd):
            return "deny", "Blocked: that command is not allowed in this test run."
        if shell_reads(cmd):
            return "allow", "read-only command"
        # a network call that sends (a plain GET piped into a script, like busy.json, is fine)
        if re.search(r"\b(nc|telnet|ftp|sftp|rsync)\b|\bcurl\b[^|;&\n]*\s(-X|--request|-d|--data\S*|-F|--form|-T|"
                     r"--upload-file|--json)(\s|=|$)", cmd):
            return "deny", "Blocked: that command is not allowed in this test run."
        if REAL_PATH.search(cmd.replace(str(root), "<sandbox>")):
            return "deny", "Blocked: that command writes outside this test's files."
        return "allow", "command in sandbox"
    if tool.startswith(("mcp__milo-google__", "mcp__milo-weather__", "mcp__milo-planner__")):
        return "allow", "faked by the eval bridge"
    if tool.startswith("mcp__claude_ai_"):
        return "deny", "This connector is not available right now. Use the milo-google tools."
    if tool in ("Task", "Agent"):
        return "deny", "Sub-agents are not available in this run. Say what you would hand off, and to which model."
    return "deny", f"{tool} is not available in this run."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--log", required=True)
    opts = ap.parse_args()
    try:
        event = json.load(sys.stdin)
    except Exception:
        event = {}
    tool, args = event.get("tool_name", ""), event.get("tool_input") or {}
    try:
        decision, reason = decide(tool, args, Path(opts.root), event.get("cwd") or opts.root)
    except Exception as e:   # fail closed
        decision, reason = "deny", f"Blocked (hook error: {e})."
    with open(opts.log, "a") as f:
        f.write(json.dumps({"ts": time.time(), "tool": tool, "input": args, "decision": decision, "reason": reason,
                            "session": event.get("session_id")}) + "\n")
    if decision == "deny":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
