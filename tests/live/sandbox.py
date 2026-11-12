"""The live suite's sandbox: a temp copy of what Milo reads and writes, laid out like ~/Documents/Milo.

  <base>/work       goose_cwd: Library (Planner, Health Tracker, Recurring tasks), Instructions, Jobs (*.md),
                    .claude/settings.json (the logging and blocking hook)
  <base>/data       MILO_DATA_DIR: config, memory, goals, schedules (copies), no secrets
  <base>/pristine   the state every case starts from
  <base>/calls.jsonl  every tool call Milo's Claude made, from the hook

Real paths in the copied instructions and schedules point at the copies, so Milo works on them as it would at home.
The codebase path (milo/) stays real: Milo may read it, and the hook blocks writes to it.
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MILO_HOME = Path(os.environ.get("MILO_EVAL_HOME") or ROOT.parent)   # ~/Documents/Milo
REAL_DATA = ROOT / "data"
LIBRARY_PARTS = ["Planner", "Health Tracker.xlsx", "Health Tracker.backup.xlsx", "Recurring tasks", "CV"]
PATH_RE = re.compile(r"(?:/Users/[^/\s]+/Documents/Milo|~/Documents/Milo)/(?=Library|Instructions|Jobs)", re.I)


def rewrite(text: str, work: Path) -> str:
    return PATH_RE.sub(str(work) + "/", text)


def copy_text_tree(src: Path, dst: Path, work: Path, pattern: str = "*.md") -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.glob(pattern)):
        if p.is_file():
            (dst / p.name).write_text(rewrite(p.read_text(), work))


def build(base: Path | None = None, port: int = 8799) -> dict:
    base = Path(base or tempfile.mkdtemp(prefix="milo-eval-")).resolve()
    work, data, pristine = base / "work", base / "data", base / "pristine"
    for d in (work, data, pristine):
        d.mkdir(parents=True, exist_ok=True)
    lib = work / "Library"
    lib.mkdir(exist_ok=True)
    for part in LIBRARY_PARTS:
        src = MILO_HOME / "Library" / part
        if src.is_dir():
            shutil.copytree(src, lib / part, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.mp4", "*.mov", "*.png", "*.jpg", "*.jpeg"))
            for md in (lib / part).rglob("*.md"):
                md.write_text(rewrite(md.read_text(), work))
        elif src.exists():
            shutil.copy2(src, lib / part)
    copy_text_tree(MILO_HOME / "Instructions", work / "Instructions", work)
    copy_text_tree(MILO_HOME / "Jobs", work / "Jobs", work)
    (work / "Jobs" / "muse-applied-jobs.md").unlink(missing_ok=True)   # a 2 MB log no case needs

    # the hook, as project settings of the sandbox (Claude Code loads <cwd>/.claude/settings.json)
    log = base / "calls.jsonl"
    log.touch()
    hook = f'"{sys.executable}" "{ROOT / "tests" / "live" / "hook.py"}" --root "{base}" --log "{log}"'
    (work / ".claude").mkdir(exist_ok=True)
    (work / ".claude" / "settings.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook}]}]}}, indent=2))

    real = json.loads((REAL_DATA / "config.json").read_text()) if (REAL_DATA / "config.json").exists() else {}
    config = {k: real[k] for k in ("assistant_name", "tone", "length", "model", "permission_mode", "compact_at")
              if k in real}
    config.update({"token": "milo-eval-token", "port": port, "goose_cwd": str(work), "library_dir": str(lib),
                   "instructions_dir": str(work / "Instructions"), "browser_enabled": False, "reactions": False,
                   "whisper_port": port + 1000, "browser_port": port + 1100, "google_client_id": "eval"})
    (data / "config.json").write_text(json.dumps(config, indent=1))
    for name in ("memory.md", "goals.json"):
        if (REAL_DATA / name).exists():
            shutil.copy2(REAL_DATA / name, data / name)
    schedules = json.loads((REAL_DATA / "schedules.json").read_text()) if (REAL_DATA / "schedules.json").exists() else []
    for s in schedules:
        s["text"] = rewrite(s.get("text") or "", work)
        s.pop("auto_approve", None)
    (data / "schedules.json").write_text(json.dumps(schedules, indent=1))

    # the start state of every case
    for name in ("Library", "Instructions", "Jobs"):
        shutil.copytree(work / name, pristine / name, dirs_exist_ok=True)
    for name in ("memory.md", "goals.json", "schedules.json"):
        if (data / name).exists():
            shutil.copy2(data / name, pristine / name)
    return {"base": base, "work": work, "data": data, "pristine": pristine, "log": log, "port": port,
            "token": config["token"]}


def reset_files(base: Path) -> None:
    """Put the copied files back as they were. The bridge reloads memory, goals and schedules itself (/api/eval/reset)."""
    work, pristine = base / "work", base / "pristine"
    for name in ("Library", "Instructions", "Jobs"):
        shutil.rmtree(work / name, ignore_errors=True)
        shutil.copytree(pristine / name, work / name)
    shutil.rmtree(work / "Temp", ignore_errors=True)   # Milo's scratch pictures (plots), empty at the start of a case
    (work / "Temp").mkdir()
