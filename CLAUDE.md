# Milo

Milo is a personal agent in the style of Meta's Muse. goose runs on a Mac with Claude (`claude-acp`), and the phone talks to it through a PWA (`web/`) over Tailscale, or through Siri. Read README.md (overview), INSTALL.md (setup) and docs/FEATURES.md (each feature) first. Notes for one machine go in CLAUDE.local.md (gitignored).

## Working on it

- `./start.sh` installs what is missing and starts the bridge. Config and token are in `data/config.json`.
- A change in `web/` reaches every open phone at once. A Python change needs a bridge restart; first check with `GET /api/state` that no chat is running or compacting.
- Run `uv run pytest -m "not agent"` (unit, API and e2e tests) after each change.
- Agent behavior (the prompts in `features.py`, the `Instructions/*.md` files, task prompts, tool wiring, reply tags, memory, compaction) is not done until the live suite passes: add or update a case in `tests/live/cases.py`, then run `uv run python tests/live/run.py --case <id>[,<id>]` (`--repeat 2` for fuzzy cases). It runs real Claude sessions in a sandbox with a fake Google. A failure is a Milo bug or a bad case: say which, and never reword a prompt just to make a case pass.
- UI: minimal, few words, Muse is the reference. `BEHAVIOR.md` (private; start it from `BEHAVIOR.example.md`) logs every reported issue with the rules learned from it. Read its rules before UI or agent-behavior work, and log new issues there.

## Rules

- `data/` has secrets (access token, VAPID key, Google tokens, browser profile). Never commit it, and never send it outside this Mac. Account passwords, 2FA secrets and the Google client secret are in the macOS Keychain (service "Milo").
- **Check for personal data before every push to GitHub.** The repo is public. Before `git push`, run `python3 scripts/check_private.py --all` and read every hit; the pre-push hook (`.githooks/pre-push`, enabled with `git config core.hooksPath .githooks`) runs the same check on what is pushed, files and commit messages, against `data/private_terms.txt` (gitignored). A hit means fix the file or the commit, never `git push --no-verify`. When a new real name, email, place, account or personal topic shows up in the work, add it to `data/private_terms.txt` first. Commit messages follow the same rule. Private material goes in gitignored files with a tracked template (`BEHAVIOR.md` and `BEHAVIOR.example.md`).
- Keep the code style of each file. Comments are short and say why.
- User-facing text: plain and short. No emoji in the UI text that you write.
