"""Live behavior suite as pytest cases (real goose + Claude turns in a sandbox; see tests/live/).

  uv run pytest -m agent tests/test_agent_behavior.py            # every case (about 40 minutes, uses the Claude plan)
  uv run pytest -m agent tests/test_agent_behavior.py -k email   # one area

tests/live/run.py runs the same cases with repeats, a table and a saved report.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "live"))

from cases import CASES  # noqa: E402
from grading import grade  # noqa: E402
from harness import Bridge  # noqa: E402

pytestmark = [pytest.mark.agent, pytest.mark.asyncio(loop_scope="module")]


@pytest.fixture(scope="module")
def eval_bridge():
    b = Bridge().start()
    yield b
    b.stop()


@pytest.mark.parametrize("case", [c for c in CASES if not c.skip], ids=lambda c: f"{c.area}-{c.id}")
async def test_live_behavior(eval_bridge, case):
    run = await eval_bridge.run_case(case)
    checks = await grade(case, run)
    failed = [f"{c['check']}: {c['detail']}" for c in checks if c["ok"] is False]
    assert not failed, f"{case.title}\nreply: {run.last.text[:600]}\n" + "\n".join(failed)
