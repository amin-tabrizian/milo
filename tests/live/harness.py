"""Runs live behavior cases against the eval bridge (bridge.py) and collects what each case needs to be graded:
the reply (raw with tags, and clean), the parsed tags, every tool call (from the sandbox hook), the fake Google calls,
the files that changed, memory, goals and schedules."""

import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import websockets

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from features import ATTR_RE, GOAL_RE, QUIET_RE, REACT_RE, REMEMBER_RE, RESTART_RE, SCHEDULE_RE, SUGGEST_RE  # noqa: E402
import sandbox  # noqa: E402

TURN_TIMEOUT = int(os.environ.get("MILO_EVAL_TURN_TIMEOUT", 420))


# what a case produced


@dataclass
class Turn:
    prompt: str
    raw: str = ""
    text: str = ""            # what the user sees (tags removed by the server)
    suggest: str = ""
    notes: list = field(default_factory=list)
    tools: list = field(default_factory=list)   # the hook's log for this turn: {tool, input, decision, reason}
    error: str | None = None
    seconds: float = 0
    spoken: str | None = None   # Siri: the text the Shortcut reads out
    started: float = 0
    ended: float = 0
    compact: bool = False       # a silent compaction (no reply)
    post: str = ""              # a task run's message as posted in the main chat ("" when none was)


@dataclass
class Run:
    case: str
    turns: list[Turn]
    google: list[dict]          # fake Google calls, in order
    google_messages: list[dict]  # drafts and sent mail, as the fake saved them
    files: dict                 # relative path -> {"before": str | None, "after": str | None, "kind": "text" | "binary"}
    memory_before: str
    memory_after: str
    schedules_before: list
    schedules_after: list
    goals_before: list
    goals_after: list
    restarts: list
    work: Path
    seconds: float = 0

    # convenience for checks
    @property
    def last(self) -> Turn:
        return self.turns[-1]

    @property
    def raw(self) -> str:
        return "\n".join(t.raw for t in self.turns)

    @property
    def tools(self) -> list[dict]:
        return [c for t in self.turns for c in t.tools]

    def tool_calls(self, pattern: str) -> list[dict]:
        return [c for c in self.tools if re.search(pattern, c["tool"])]

    def google_calls(self, name: str) -> list[dict]:
        return [c for c in self.google if c["tool"] == name]

    def shell(self) -> list[str]:
        return [str(c["input"].get("command", "")) for c in self.tools if c["tool"] == "Bash"]

    def changed(self, pattern: str = "") -> dict:
        return {p: d for p, d in self.files.items() if re.search(pattern, p)}

    def added_lines(self, path_pattern: str) -> list[str]:
        out = []
        for p, d in self.changed(path_pattern).items():
            if d["kind"] != "text":
                continue
            before = (d["before"] or "").splitlines()
            after = (d["after"] or "").splitlines()
            out += [ln[1:] for ln in difflib.unified_diff(before, after, lineterm="", n=0)
                    if ln.startswith("+") and not ln.startswith("+++")]
        return out


def tags(raw: str) -> dict:
    """The reply tags, parsed the way features.py reads them."""
    return {
        "suggest": [s.strip() for s in SUGGEST_RE.findall(raw)],
        "remember": [s.strip() for s in REMEMBER_RE.findall(raw)],
        "schedule": [{**dict(ATTR_RE.findall(a)), "text": b.strip()} for a, b in SCHEDULE_RE.findall(raw)],
        "goal": [{**dict(ATTR_RE.findall(a)), "text": b.strip()} for a, b in GOAL_RE.findall(raw)],
        "react": [b.strip() for _, b in REACT_RE.findall(raw)],
        "restart": bool(RESTART_RE.search(raw)),
        "quiet": bool(QUIET_RE.search(raw)),
    }


# the files a case may change


def snapshot(work: Path) -> dict:
    out = {}
    for p in work.rglob("*"):
        if p.is_file() and ".claude" not in p.relative_to(work).parts:
            rel = str(p.relative_to(work))
            data = p.read_bytes()
            if p.suffix in (".md", ".txt", ".json", ".csv", ".tex"):
                out[rel] = ("text", data.decode(errors="replace"))
            else:
                out[rel] = ("binary", hashlib.sha256(data).hexdigest())
    return out


def diff_snapshots(a: dict, b: dict) -> dict:
    changed = {}
    for rel in set(a) | set(b):
        if a.get(rel) != b.get(rel):
            kind = (b.get(rel) or a.get(rel))[0]
            changed[rel] = {"kind": kind, "before": a[rel][1] if rel in a else None,
                            "after": b[rel][1] if rel in b else None}
    return changed


# the bridge


def sweep_transcripts() -> None:
    """Claude Code's transcripts of old sandboxes, in Milo's profile (goose may write them after the bridge stops)."""
    for d in (ROOT / "data" / "claude" / "projects").glob("*-milo-eval-*-work"):
        sandbox_dir = next((p for p in Path(tempfile.gettempdir()).resolve().glob("milo-eval-*")
                            if re.sub(r"[^A-Za-z0-9-]", "-", str(p / "work")) == d.name), None)
        if sandbox_dir is None:
            shutil.rmtree(d, ignore_errors=True)


class Bridge:
    def __init__(self, port: int | None = None, keep: bool = False):
        self.port = port or int(os.environ.get("MILO_EVAL_PORT", 8799))
        self.keep = keep
        self.box: dict = {}
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.box['token']}"}

    def start(self) -> "Bridge":
        sweep_transcripts()
        self.box = sandbox.build(port=self.port)
        env = {**os.environ, "MILO_DATA_DIR": str(self.box["data"]),
               "MILO_CLAUDE_DIR": str(ROOT / "data" / "claude"),   # Milo's signed-in Claude profile, as in production
               "MILO_KEYCHAIN_SERVICE": f"Milo-eval-{uuid.uuid4().hex[:8]}",   # no saved logins or Google secret
               "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}   # claude.ai Gmail/Calendar/Slack reach real accounts
        self.log = open(self.box["base"] / "bridge.log", "w")
        self.proc = subprocess.Popen([sys.executable, str(HERE / "bridge.py"), "--base", str(self.box["base"])],
                                     cwd=ROOT, env=env, stdout=self.log, stderr=self.log)
        for _ in range(240):
            if self.proc.poll() is not None:
                break
            try:
                if httpx.get(f"{self.base_url}/api/state", headers=self.headers, timeout=1).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError("eval bridge did not start:\n" + (self.box["base"] / "bridge.log").read_text()[-3000:])

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.box and not self.keep:
            shutil.rmtree(self.box["base"], ignore_errors=True)
        sweep_transcripts()

    def api(self, method: str, path: str, **kw):
        r = httpx.request(method, f"{self.base_url}{path}", headers=self.headers, timeout=60, **kw)
        r.raise_for_status()
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text

    def log_lines(self) -> int:
        return len(self.box["log"].read_text().splitlines())

    def calls_since(self, n: int) -> list[dict]:
        return [json.loads(x) for x in self.box["log"].read_text().splitlines()[n:] if x.strip()]

    # one case

    async def run_case(self, case) -> Run:
        self.api("POST", "/api/eval/reset")
        if case.setup:
            self.api("POST", "/api/eval/setup", json=case.setup())
        before = self.api("GET", "/api/eval/info")
        files_before = snapshot(self.box["work"])
        t0 = time.time()
        turns: list[Turn] = []
        conv = None
        async with websockets.connect(f"ws://127.0.0.1:{self.port}/ws?token={self.box['token']}", max_size=None) as ws:
            for step in case.turns:
                turn = Turn(prompt=step.get("text") or ("compact" if step.get("compact") else
                                                         f"(the scheduled task {step.get('run_schedule')} ran)"))
                mark = self.log_lines()
                turn.started = started = time.time()
                try:
                    if step.get("siri"):
                        conv, msg, spoken = await self._siri(ws, step["text"])
                        turn.spoken = spoken
                    elif step.get("compact"):
                        turn.compact = True
                        await self._idle()
                        msg = await self._compact(conv)
                    elif step.get("run_schedule"):
                        conv, msg = await self._scheduled(ws, step["run_schedule"])
                    else:
                        conv, msg = await self._prompt(ws, step["text"], conv, bool(step.get("voice")))
                    turn.raw, turn.text = msg.get("raw", ""), msg.get("text", "")
                    turn.post = (msg.get("post") or {}).get("text", "")
                    turn.suggest, turn.notes, turn.error = msg.get("suggest", ""), msg.get("notes", []), msg.get("error")
                except Exception as e:   # a timeout or a dead bridge fails the case, not the run
                    turn.error = f"{type(e).__name__}: {e}"
                await asyncio.sleep(0.5)
                turn.tools = self.calls_since(mark)
                turn.ended = time.time()
                turn.seconds = round(turn.ended - started, 1)
                turns.append(turn)
                if turn.error:
                    break
        await self._idle()
        after = self.api("GET", "/api/eval/info")
        return Run(case=case.id, turns=turns, google=after["google_calls"], google_messages=after["google_messages"],
                   files=diff_snapshots(files_before, snapshot(self.box["work"])),
                   memory_before=before["memory"], memory_after=after["memory"],
                   schedules_before=before["schedules"], schedules_after=after["schedules"],
                   goals_before=before["goals"], goals_after=after["goals"], restarts=after["restarts"],
                   work=self.box["work"], seconds=round(time.time() - t0, 1))

    async def _idle(self, timeout: float = 60) -> None:
        """A compaction or a queued turn after the case would spill into the next one."""
        end = time.time() + timeout
        while time.time() < end and self.api("GET", "/api/eval/info")["busy"]:
            await asyncio.sleep(1)

    @staticmethod
    async def _wait_done(ws, conv_of, deadline: float):
        conv = None
        while time.time() < deadline:
            ev = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.time()))
            conv = conv_of(ev) or conv
            if ev.get("t") == "done" and conv and ev.get("id") == conv:
                return conv, ev["message"]
        raise TimeoutError("no reply in time")

    async def _prompt(self, ws, text: str, conv: str | None, voice: bool):
        ref = uuid.uuid4().hex[:8]
        await ws.send(json.dumps({"type": "prompt", "id": conv, "text": text, "ref": ref, "voice": voice}))
        return await self._wait_done(ws, lambda ev: ev.get("id") if ev.get("t") == "bound" and ev.get("ref") == ref
                                     else None, time.time() + TURN_TIMEOUT)

    async def _compact(self, conv: str) -> dict:
        """As Milo after a long turn: the chat compacts silently into a new session. The app shows nothing."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=TURN_TIMEOUT) as c:
            (await c.post(f"/api/conversations/{conv}/compact")).raise_for_status()
        return {"text": "", "raw": ""}

    async def _siri(self, ws, text: str):
        """As the Siri Shortcut: POST /api/ask, which answers in the main chat with a voice turn."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=TURN_TIMEOUT) as c:
            ask = asyncio.create_task(c.post("/api/ask", json={"text": text}))
            main = None
            for _ in range(40):
                state = (await c.get("/api/state")).json()
                main = next((x["id"] for x in state["conversations"] if x.get("main")), None)
                if main:
                    break
                await asyncio.sleep(0.25)
            conv, msg = await self._wait_done(ws, lambda ev: main, time.time() + TURN_TIMEOUT)
            spoken = (await ask).text
        return conv, msg, spoken

    async def _scheduled(self, ws, schedule_id: str):
        """As the scheduler: one run of a scheduled task, in its hidden chat, with the app's scheduled-run prompt. The
        turn is graded on that chat's whole reply (raw, with tags). A reply that is not quiet is then posted in the
        main chat, and the case's next message goes there, as the user would answer it. post: the posted message."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=60) as c:
            run = asyncio.create_task(c.post(f"/api/schedules/{schedule_id}/run"))

            def conv_of(ev):
                c = ev.get("conv") if ev.get("t") == "conv" else None
                return c["id"] if c and c.get("source") == "scheduled" else None
            conv, msg = await self._wait_done(ws, conv_of, time.time() + TURN_TIMEOUT)
            (await run).raise_for_status()
            main = None
            if msg.get("text") and not msg.get("error") and not re.search(r"<quiet\s*/>", msg.get("raw", "")):
                deadline = time.time() + 30
                try:
                    while time.time() < deadline and not main:
                        ev = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.time()))
                        if ev.get("t") == "message":
                            main, msg["post"] = ev["id"], ev["message"]
                except TimeoutError:   # no post: the case's checks on post say so
                    pass
        return main or conv, msg


def now() -> datetime:
    return datetime.now().astimezone()
