"""Minimal Agent Client Protocol (ACP) client that drives `goose acp` over stdio."""

import asyncio
import itertools
import json
import logging
import os
import re
import signal
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("acp")

UpdateHandler = Callable[[str, dict], Awaitable[None]]
# (sessionId, toolCall, options) -> chosen optionId, or None to cancel
PermissionHandler = Callable[[str, dict, list[dict]], Awaitable[str | None]]

GOOSE_DB = Path(os.environ.get("MILO_GOOSE_DB") or Path.home() / ".local/share/goose/sessions/sessions.db")
CLAUDE_SESSION_ARG = re.compile(r"--(?:resume|session-id)[= ]([0-9a-fA-F-]{36})(?:\s|$)")
PROVIDER_SESSION = "json_extract(metadata_json, '$.inference.providerSessionId')"


def _goose_db(query: str, args: tuple, db_path: Path | None) -> list[tuple]:
    try:
        db = sqlite3.connect(f"file:{db_path or GOOSE_DB}?mode=ro", uri=True, timeout=2)
        try:
            return db.execute(query, args).fetchall()
        finally:
            db.close()
    except sqlite3.Error as e:
        log.warning("can't read goose's sessions: %s", e)
        return []


def claude_session(sid: str, db_path: Path | None = None) -> str | None:
    """The Claude Code session behind goose session sid. goose records it on a turn's replies when the turn ends."""
    rows = _goose_db(f"SELECT {PROVIDER_SESSION} AS p FROM messages WHERE session_id = ? AND p IS NOT NULL "
                     "ORDER BY id DESC LIMIT 1", (sid,), db_path)
    return rows[0][0] if rows else None


def recorded_claude_sessions(db_path: Path | None = None) -> set[str]:
    return {r[0] for r in _goose_db(f"SELECT DISTINCT {PROVIDER_SESSION} AS p FROM messages WHERE p IS NOT NULL", (),
                                    db_path)}


def claude_procs(root: int, ps: str | None = None) -> dict[int, str]:
    """The Claude Code processes under process root, with the Claude session each one runs."""
    if ps is None:
        ps = subprocess.run(["ps", "-ax", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    kids: dict[int, list[tuple[int, str]]] = {}
    for line in ps.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append((int(parts[0]), parts[2] if len(parts) > 2 else ""))
    found, todo = {}, [root]
    while todo:
        for pid, cmd in kids.get(todo.pop(), []):
            todo.append(pid)
            if m := CLAUDE_SESSION_ARG.search(cmd):
                found[pid] = m.group(1)
    return found


class AcpError(RuntimeError):
    pass


class GooseAcp:
    def __init__(self, cwd: str, on_update: UpdateHandler, on_permission: PermissionHandler, mode: str = "smart_approve",
                 model: str | None = None, claude_dir: str | None = None):
        self.cwd = cwd
        self.on_update = on_update
        self.on_permission = on_permission
        # With the claude-acp provider, GOOSE_MODE must be set when the process starts;
        # session/set_mode afterwards does not reach Claude Code's permission layer.
        self.mode = mode
        self.model = model   # GOOSE_MODEL; None keeps the model in goose's config
        # CLAUDE_CONFIG_DIR for claude-acp: Milo's own Claude profile, so it never shares memory or settings with
        # the Claude profile of the shell that started the bridge
        self.claude_dir = claude_dir
        self.proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._loaded: set[str] = set()
        self._prompting: set[str] = set()
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            "goose", "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
            env={**os.environ, "GOOSE_MODE": self.mode, **({"GOOSE_MODEL": self.model} if self.model else {}),
                 **({"CLAUDE_CONFIG_DIR": self.claude_dir} if self.claude_dir else {})},
        )
        self._loaded.clear()
        self._reader = asyncio.create_task(self._read_loop())
        await self.request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        })
        log.info("goose acp started (pid %s)", self.proc.pid)

    async def ensure_running(self) -> None:
        async with self._lock:
            if self.proc is None or self.proc.returncode is not None:
                await self.start()

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()

    async def restart(self, mode: str) -> None:
        async with self._lock:
            self.mode = mode
            await self.stop()
            if self._reader:
                await asyncio.gather(self._reader, return_exceptions=True)
            await self.start()

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        async for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                await self._dispatch(msg)
            except Exception:
                log.exception("error handling ACP message")
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(AcpError("goose acp exited"))
        self._pending.clear()
        log.warning("goose acp exited")

    async def _dispatch(self, msg: dict) -> None:
        if "method" not in msg:
            fut = self._pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(AcpError(msg["error"].get("message", str(msg["error"]))))
                else:
                    fut.set_result(msg.get("result"))
            return

        method, params = msg["method"], msg.get("params", {})
        if method == "session/update":
            await self.on_update(params.get("sessionId", ""), params.get("update", {}))
        elif "id" in msg:
            # Answer in a task: a permission request waits for the user, and the read loop must keep going.
            asyncio.create_task(self._answer_agent_request(msg["id"], method, params))

    async def _answer_agent_request(self, req_id: Any, method: str, params: dict) -> None:
        if method == "session/request_permission":
            try:
                choice = await self.on_permission(params.get("sessionId", ""), params.get("toolCall", {}), params.get("options", []))
            except Exception:
                log.exception("permission handler failed")
                choice = None
            outcome = {"outcome": "selected", "optionId": choice} if choice else {"outcome": "cancelled"}
            await self._send({"jsonrpc": "2.0", "id": req_id, "result": {"outcome": outcome}})
        else:
            await self._send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unsupported: {method}"}})

    async def _send(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict) -> Any:
        req_id = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return await fut

    async def notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # Session helpers

    async def new_session(self, mcp_servers: list[dict] | None = None) -> str:
        await self.ensure_running()
        result = await self.request("session/new", {"cwd": self.cwd, "mcpServers": mcp_servers or []})
        sid = result["sessionId"]
        self._loaded.add(sid)
        return sid

    async def load_session(self, sid: str, mcp_servers: list[dict] | None = None) -> None:
        """Load a session that this goose process has not seen yet. Replayed history is ignored by the caller."""
        await self.ensure_running()
        if sid in self._loaded:
            return
        await self.request("session/load", {"sessionId": sid, "cwd": self.cwd, "mcpServers": mcp_servers or []})
        self._loaded.add(sid)

    def is_loaded(self, sid: str) -> bool:
        return sid in self._loaded

    def loaded(self) -> set[str]:
        return set(self._loaded)

    async def close_session(self, sid: str) -> None:
        """End the claude-agent-acp and Claude Code processes of session sid (about 400 MB). Its next prompt loads it
        again, with its whole history. Without this every session kept them until goose exited: 32 sessions filled
        the 16 GB Mac and it hung (2026-10-21)."""
        async with self._lock:   # a turn that starts meanwhile waits in ensure_running, then loads the session again
            if sid not in self._loaded or sid in self._prompting or not self.proc or self.proc.returncode is not None:
                return
            self._loaded.discard(sid)
            await self.request("session/close", {"sessionId": sid})

    async def prompt(self, sid: str, blocks: list[dict]) -> dict:
        await self.load_session(sid)
        self._prompting.add(sid)
        try:
            return await self.request("session/prompt", {"sessionId": sid, "prompt": blocks})
        finally:
            self._prompting.discard(sid)

    async def cancel(self, sid: str) -> None:
        if self.proc and self.proc.returncode is None:
            await self.notify("session/cancel", {"sessionId": sid})

    async def interrupt(self, sid: str) -> bool:
        """Stop the Claude Code process behind session sid, after cancel. goose ends the turn on session/cancel but does
        not pass the cancel on to claude-acp (goose 1.55), so Claude's tools and subagents went on running. SIGINT
        stops it like Esc and saves the transcript. The process exits, so the session must be forked before its next
        prompt."""
        if not self.proc or self.proc.returncode is not None:
            return False
        procs = await asyncio.to_thread(claude_procs, self.proc.pid)
        claude_sid = None
        for _ in range(15):   # goose records the turn's Claude session as the cancel ends the turn
            claude_sid = await asyncio.to_thread(claude_session, sid)
            if claude_sid:
                break
            await asyncio.sleep(0.2)
        if claude_sid:
            pids = [pid for pid, c in procs.items() if c == claude_sid]
        else:   # a first turn stopped before Claude said anything: the one Claude goose has no record of
            recorded = await asyncio.to_thread(recorded_claude_sessions)
            new = [pid for pid, c in procs.items() if c not in recorded]
            pids = new if len(new) == 1 else []
        if not pids:
            log.warning("no Claude Code process to stop for session %s", sid)
            return False
        for pid in pids:
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        for _ in range(50):   # until it has saved the transcript and exited, so the fork resumes all of it
            await asyncio.sleep(0.1)
            alive = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except ProcessLookupError:
                    pass
            if not alive:
                break
        log.info("stopped Claude Code %s for session %s", pids, sid)
        return True

    async def fork_session(self, sid: str, mcp_servers: list[dict] | None = None) -> str:
        """A new goose session with sid's history. Its claude-acp resumes the same Claude Code session."""
        await self.ensure_running()
        result = await self.request("session/fork", {"sessionId": sid, "cwd": self.cwd, "mcpServers": mcp_servers or []})
        new = result["sessionId"]
        self._loaded.add(new)
        return new
