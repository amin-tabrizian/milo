"""Keeps real people's names, emails and other private details out of git, and keeps them in the files on this Mac.

data/private.json lists [real, fake] pairs (data/ is never committed). A git filter ("private", set up by
`python3 private.py install`) puts the fake text in every commit and the real text back on checkout. A pre-commit
hook refuses a commit that still has a real value in it, for example from a file type that the filter skips.
A clone without data/private.json gets the fake text and no filter.

Usage: private.py clean|smudge (git runs these) | install | check"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MAP = Path(os.environ.get("MILO_PRIVATE_MAP") or ROOT / "data" / "private.json")
HOOK = """#!/bin/sh
# Milo: no real names or emails in a commit (private.py)
exec python3 private.py check
"""


def pairs() -> list[tuple[str, str]]:
    return [tuple(p) for p in json.loads(MAP.read_text())] if MAP.exists() else []


def swap(text: str, pairs: list[tuple[str, str]], back: bool = False) -> str:
    """Real -> fake (back: fake -> real). Whole words only, longest first, so "Bo" leaves "Jimbo" alone. A word
    right after a \\n or \\t escape in source code ("Thanks,\\nBo") counts as a whole word too."""
    table = {f: r for r, f in pairs} if back else dict(pairs)
    if not table:
        return text
    words = sorted(table, key=len, reverse=True)
    pattern = re.compile("|".join(rf"(?:(?<!\w)|(?<=\\[nt])){re.escape(w)}(?!\w)" for w in words))
    return pattern.sub(lambda m: table[m.group(0)], text)


def filter_stdin(back: bool) -> None:
    data = sys.stdin.buffer.read()
    try:
        text = data.decode()
    except UnicodeDecodeError:   # not text: as it is
        sys.stdout.buffer.write(data)
        return
    sys.stdout.buffer.write(swap(text, pairs(), back).encode())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def check() -> int:
    """Exit 1 when a staged file still holds a real value."""
    found = []
    for real, _ in pairs():
        found += [f"{line}  ({real!r})" for line in git("grep", "--cached", "-n", "-w", "-F", "-I", "-e", real).splitlines()]
    if found:
        print("private.py: real names or emails in the commit. Add them to data/private.json, then "
              "`git add --renormalize .`:\n  " + "\n  ".join(found[:20]), file=sys.stderr)
    return 1 if found else 0


def install() -> None:
    py = f"python3 {ROOT / 'private.py'}"
    subprocess.run(["git", "config", "filter.private.clean", f"{py} clean"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "filter.private.smudge", f"{py} smudge"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "filter.private.required", "true"], cwd=ROOT, check=True)
    hook = Path(git("rev-parse", "--git-path", "hooks").strip())
    hook = (hook if hook.is_absolute() else ROOT / hook) / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK)
    hook.chmod(0o755)
    subprocess.run(["git", "add", "--renormalize", "."], cwd=ROOT, check=True)
    print(f"private filter on: {len(pairs())} pairs from {MAP}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("clean", "smudge"):
        filter_stdin(back=cmd == "smudge")
    elif cmd == "install":
        install()
    elif cmd == "check":
        sys.exit(check())
    else:
        sys.exit(__doc__)
