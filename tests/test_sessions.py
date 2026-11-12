"""A closed goose session ends its Claude Code processes, and its next prompt loads it with its history (bug of
2026-10-21: every session kept its processes until goose exited, 32 of them filled the Mac's memory and it hung).

  uv run pytest tests/test_sessions.py -m agent   a real goose and Claude (about 20 s, a little of your Claude plan;
                                                  start it from Terminal, since SSH can't read the Keychain)
"""

import asyncio
import os
from pathlib import Path

import pytest

from acp import GooseAcp

ROOT = Path(__file__).resolve().parents[1]


def children(pid: int) -> int:
    return sum(1 for line in os.popen("ps -ax -o ppid=").read().split() if line == str(pid))


@pytest.mark.agent
def test_closed_session_frees_claude_and_loads_again(tmp_path):
    said = []

    async def update(sid, u):
        if u.get("sessionUpdate") == "agent_message_chunk":
            said.append(u.get("content", {}).get("text", ""))

    async def allow(sid, tool, options):
        return options[0]["optionId"]

    async def run():
        goose = GooseAcp(str(tmp_path), update, allow, "auto", os.environ.get("MILO_TEST_MODEL", "claude-haiku-5-5"),
                         os.environ.get("MILO_CLAUDE_DIR") or str(ROOT / "data" / "claude"))
        await goose.start()
        try:
            sid = await goose.new_session()
            await goose.prompt(sid, [{"type": "text", "text": "The code word is PELICAN-42. Reply with just: ok"}])
            assert children(goose.proc.pid) == 1   # claude-agent-acp, with Claude Code under it
            await goose.close_session(sid)
            await asyncio.sleep(3)
            assert children(goose.proc.pid) == 0 and not goose.is_loaded(sid)
            await goose.load_session(sid)
            said.clear()   # the replayed history
            result = await goose.prompt(sid, [{"type": "text", "text": "What is the code word? Just the word."}])
            assert result["stopReason"] == "end_turn"
            assert "PELICAN-42" in "".join(said), "".join(said)
        finally:
            await goose.stop()

    asyncio.run(run())
