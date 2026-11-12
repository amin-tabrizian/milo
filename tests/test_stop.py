"""Stop must stop Claude Code itself, not only goose's turn (bug of 2026-10-20: a subagent ran on after Stop).

  uv run pytest tests/test_stop.py            finding the right Claude process (no goose needed)
  uv run pytest tests/test_stop.py -m agent   a real goose and Claude: Stop ends a running command, and the chat
                                              goes on with its history (about 40 s, a little of your Claude plan;
                                              start it from Terminal, since SSH can't read the Keychain)
"""

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from acp import GooseAcp, claude_procs, claude_session, recorded_claude_sessions

ROOT = Path(__file__).resolve().parents[1]

A = "0924b84d-e7a3-495b-929b-a04762d90d2b"
B = "c453aa0a-c142-4dd5-859b-33d86719497b"
PS = f"""\
  100     1 goose acp
  101   100 node /opt/homebrew/bin/claude-agent-acp
  102   101 /opt/homebrew/lib/node_modules/claude --output-format stream-json --resume={A} --tools=default
  103   102 /bin/zsh -c sleep 100 --resume={B}x
  201   100 node /opt/homebrew/bin/claude-agent-acp
  202   201 /opt/homebrew/lib/node_modules/claude --output-format stream-json --session-id={B}
  301     1 /opt/homebrew/lib/node_modules/claude --resume={A}
"""


def test_claude_procs_under_this_goose():
    # a new session runs with --session-id, a loaded one with --resume; 301 is another goose's, 103 no session arg
    assert claude_procs(100, PS) == {102: A, 202: B}
    assert claude_procs(999, PS) == {}


def test_claude_session_is_the_latest_one_goose_recorded(tmp_path):
    db = tmp_path / "sessions.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, metadata_json TEXT)")
    meta = lambda p: json.dumps({"inference": {"provider": "claude-acp", "providerSessionId": p}} if p else {})
    con.executemany("INSERT INTO messages (session_id, metadata_json) VALUES (?, ?)",
                    [("s1", meta(None)), ("s1", meta("old")), ("s1", meta("new")), ("s1", meta(None)), ("s2", meta("x"))])
    con.commit()
    con.close()
    assert claude_session("s1", db) == "new"
    assert claude_session("s3", db) is None
    assert claude_session("s1", tmp_path / "missing.db") is None
    assert recorded_claude_sessions(db) == {"old", "new", "x"}


@pytest.mark.agent
def test_stop_ends_claudes_work_and_the_chat_goes_on(tmp_path):
    beat = tmp_path / "beat.txt"
    beat.touch()
    loop = f"for i in $(seq 1 40); do date +%T >> {beat}; sleep 2; done"
    said = []

    async def update(sid, u):
        if u.get("sessionUpdate") == "agent_message_chunk":
            said.append(u.get("content", {}).get("text", ""))

    async def allow(sid, tool, options):
        return options[0]["optionId"]

    def beats():
        return len(beat.read_text().split())

    async def run():
        goose = GooseAcp(str(tmp_path), update, allow, "auto", os.environ.get("MILO_TEST_MODEL", "claude-haiku-5-5"),
                         os.environ.get("MILO_CLAUDE_DIR") or str(ROOT / "data" / "claude"))
        await goose.start()
        try:
            sid = await goose.new_session()
            turn = asyncio.create_task(goose.prompt(sid, [{"type": "text", "text":
                "Use the Agent tool (general-purpose, in the foreground) and give it this task: run this exact shell "
                f"command with the Bash tool in the foreground, timeout 600000 ms, then say done: {loop}"}]))
            start = time.time()
            while beats() < 2:
                assert time.time() - start < 180 and not turn.done(), "the command never started"
                await asyncio.sleep(0.5)
            await goose.cancel(sid)
            assert await goose.interrupt(sid)
            assert (await asyncio.wait_for(turn, 30))["stopReason"] == "cancelled"
            n = beats()
            await asyncio.sleep(8)
            assert beats() == n, "the command went on after Stop"
            fork = await goose.fork_session(sid)
            said.clear()
            result = await goose.prompt(fork, [{"type": "text", "text":
                "Which file did the command I asked for write to? Answer with the file name only."}])
            assert result["stopReason"] == "end_turn"
            assert beat.name in "".join(said), "".join(said)
        finally:
            await goose.stop()

    asyncio.run(run())
