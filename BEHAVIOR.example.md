# Behavior log

Template for `BEHAVIOR.md`. Git ignores `BEHAVIOR.md`, because its log holds your words. To start your log, copy this file to `BEHAVIOR.md`.

`BEHAVIOR.md` records each issue that you report about how Milo looks or acts, and the rules that come from these issues. Code comments and tests refer to entries as "BEHAVIOR #N".

- When you report an issue, add an entry to the log. If a rule applies, add the entry number to the rule. If the entry shows a new pattern, write a new rule.
- Before you do UI work or agent-behavior work, read the rules.

## Rules

1. **Muse is the reference.** Before you change how something looks or moves, examine how Muse does it, and do the same.
2. **Agent behavior is proven live.** A change to prompts, instructions, tools or tags gets a case in `tests/live/cases.py`, and the live suite must pass.
3. **Milo is one person in one conversation.** Work that Milo does alone comes to the main chat as its own message. Session details never show.

## Log

| # | Date | You said | What was wrong | Fix / status |
|---|---|---|---|---|
| 1 | 2026-01-05 | "Milo made a second task when I only asked it to change the time of the first one." | Milo made a new task and paused the old task. | Milo edits a task in place, after you approve the change. |
