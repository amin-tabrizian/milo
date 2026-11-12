#!/usr/bin/env python3
"""Block a push that would publish personal data: the files and commit messages being pushed must not match any
pattern in data/private_terms.txt (gitignored: the list itself is private).

  scripts/check_private.py          as the pre-push hook (.githooks/pre-push; git passes the refs on stdin)
  scripts/check_private.py --all    check HEAD's files and every commit message, before a first push

Terms: one Python regex per line, matched without case; blank lines and lines starting with # are skipped. Add every
new real name, email, place or account there before it can reach a commit. Never push with --no-verify.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS = ROOT / "data" / "private_terms.txt"
SKIP = ("web/vendor/", "uv.lock", "scripts/private_terms.example.txt")   # third-party code, hashes, the template
ZERO = "0" * 40


def git(*args: str, ok=(0,)) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"check_private: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def load_terms() -> list[re.Pattern]:
    if not TERMS.exists():
        sys.exit(f"check_private: {TERMS.relative_to(ROOT)} is missing, so nothing can be checked. Create it from "
                 "scripts/private_terms.example.txt (one regex per line) and push again.")
    terms = []
    for line in TERMS.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            terms.append(re.compile(line.strip(), re.I))
    return terms


def file_hits(commit: str, terms: list[re.Pattern]) -> list[str]:
    files = [f for f in git("ls-tree", "-r", "--name-only", commit).stdout.split("\n") if not f.startswith(SKIP)]
    hits = []
    for path in filter(None, files):
        blob = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True).stdout
        if b"\0" in blob[:8000]:   # binary
            continue
        for n, line in enumerate(blob.decode("utf-8", "replace").splitlines(), 1):
            for t in terms:
                if t.search(line):
                    hits.append(f"{path}:{n}: /{t.pattern}/ in {line.strip()[:100]!r}")
    return hits


def message_hits(rev_range: list[str], terms: list[re.Pattern]) -> list[str]:
    log = git("log", "--format=%H%x00%B%x01", *rev_range).stdout
    hits = []
    for entry in filter(None, log.split("\x01")):
        sha, _, body = entry.strip("\n").partition("\x00")
        for t in terms:
            if t.search(body):
                hits.append(f"commit {sha[:10]} message: /{t.pattern}/")
    return hits


def main() -> int:
    terms = load_terms()
    hits: list[str] = []
    if "--all" in sys.argv:
        hits = file_hits("HEAD", terms) + message_hits(["HEAD"], terms)
    else:
        for line in sys.stdin.read().splitlines():
            local_ref, local_sha, _, remote_sha = line.split()
            if local_sha == ZERO:   # a delete pushes no content
                continue
            hits += file_hits(local_sha, terms)
            hits += message_hits([local_sha] if remote_sha == ZERO else [f"{remote_sha}..{local_sha}"], terms)
    if hits:
        print("Push blocked: personal data would be published (data/private_terms.txt):", file=sys.stderr)
        for h in hits[:50]:
            print("  " + h, file=sys.stderr)
        if len(hits) > 50:
            print(f"  ... and {len(hits) - 50} more", file=sys.stderr)
        return 1
    print(f"check_private: no personal data found ({len(terms)} terms).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
