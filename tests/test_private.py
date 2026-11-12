"""The git filter that keeps real names out of commits (private.py)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import private

ROOT = Path(__file__).parent.parent
# invented names: real ones in this file would be swapped too
PAIRS = [("Nora Vance", "Ivy Hale"), ("Nora", "Ivy"), ("nvance@uni.test", "ihale@school.example.edu"),
         ("Bo", "Lu"), ("9 Quill Ln", "42 Elm St")]


def test_swap_is_whole_words_longest_first_and_round_trips():
    text = 'From: Nora Vance <nvance@uni.test>\nHi Nora, Bo and Jimbo. Noras, "Bo/Alex", ev-bo.\n9 Quill Ln'
    fake = private.swap(text, PAIRS)
    assert fake == ('From: Ivy Hale <ihale@school.example.edu>\nHi Ivy, Lu and Jimbo. Noras, "Lu/Alex", '
                    'ev-bo.\n42 Elm St')
    assert private.swap(fake, PAIRS, back=True) == text
    assert private.swap(text, []) == text                       # no map (a clone): as it is
    code = r'"body": "Hi all,\n\nThanks,\nNora Vance\nBo\tBo"'      # source code: escapes, not line breaks
    assert private.swap(code, PAIRS) == r'"body": "Hi all,\n\nThanks,\nIvy Hale\nLu\tLu"'
    assert private.swap(r"\nNoras", PAIRS) == r"\nNoras"


def run(cmd, data: bytes, mapfile: Path) -> bytes:
    env = {**os.environ, "MILO_PRIVATE_MAP": str(mapfile)}
    return subprocess.run([sys.executable, str(ROOT / "private.py"), cmd], input=data, env=env,
                          capture_output=True, check=True).stdout


def test_clean_and_smudge_through_git(tmp_path):
    mapfile = tmp_path / "private.json"
    mapfile.write_text(json.dumps(PAIRS))
    assert run("clean", b"Thanks,\nNora Vance\n", mapfile) == b"Thanks,\nIvy Hale\n"
    assert run("smudge", b"Thanks,\nIvy Hale\n", mapfile) == b"Thanks,\nNora Vance\n"
    png = b"\x89PNG\r\n\x1a\n\xff\xfeNora"
    assert run("clean", png, mapfile) == png                   # not text: untouched
    assert run("clean", b"Nora", tmp_path / "missing.json") == b"Nora"


@pytest.mark.skipif(not private.MAP.exists(), reason="no data/private.json on this machine")
def test_fakes_are_new_words():
    """A fake that is already in the code would turn into the real word on the next checkout."""
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    texts = {f: (ROOT / f).read_text(errors="ignore") for f in files if (ROOT / f).suffix in (".py", ".md", ".js", ".json", ".html")}
    for real, fake in private.pairs():
        hits = [f for f, t in texts.items() if private.swap(t, [(fake, "\0")]) != t]
        assert not hits, f"fake {fake!r} (for {real!r}) is already in {hits}"
