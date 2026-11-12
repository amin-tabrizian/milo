# Milo features

What Milo does, and where each part is in the code. To install Milo, see [INSTALL.md](../INSTALL.md).

## What it does

- **One main chat.** Milo opens on one chat that continues, like a conversation with a person. Side chats are for separate topics. You cannot clear a chat. Milo compacts long chats automatically, and you do not see it.
- **Conversation log.** Every message is kept on the Mac, one Markdown file a day in `~/Documents/Milo/Conversations`.
- **Chat and voice.** Type, hold the mic to talk, or use the hands-free voice mode. Speech-to-text (whisper.cpp) and text-to-speech (Kokoro) run on the Mac.
- **Background work and alerts.** Tasks continue on the Mac after you close the app. A push alert comes when a task is done.
- **Approval cards.** Before Milo sends, deletes, buys or runs something that changes data, the phone asks you.
- **Memory, goals and ideas.** Milo keeps short facts about you and your goals in every chat. Ideas are tasks that Milo offers to do.
- **Scheduled tasks.** "Every weekday at 8, brief me." A task runs out of view, and its message comes to the main chat. When you answer, Milo completes the task.
- **To-dos and planning.** `Library/Planner/Tasks.md` holds your to-dos with due dates, estimates and planned work blocks. The milo-planner tools read all calendars and the to-do list, and check each plan against the rules in `Instructions/Planning rules.md`. A calendar event changes only after you agree.
- **Google accounts.** Gmail, Calendar and Drive for many accounts, through workspace-mcp.
- **Browser.** Milo has its own Chrome. You can watch it from the phone, take control and give it back. Passwords stay in the macOS Keychain.
- **Library.** Milo puts its files in `~/Documents/Milo/Library`. The app shows photos, PDFs, Markdown, CSV and text.
- **Feed.** A short brief of your X timelines, with the top posts.
- **Hey Siri.** `POST /api/ask`. Siri speaks a short answer, and the chat keeps the full reply.

## Files

| Path | Contents |
|---|---|
| `server.py` | Bridge: HTTP API, WebSocket, Siri endpoint |
| `acp.py` | Client for `goose acp` (Agent Client Protocol) |
| `features.py` | Prompts, memory, goals, ideas, activity, library, scheduler, web push |
| `planner_mcp.py` | `milo-planner` MCP server: day view, plan check, workload, work blocks |
| `google_mcp.py` | `milo-google` MCP server: Google accounts through workspace-mcp |
| `browser.py`, `browser_mcp.py` | Milo's Chrome and the `milo-browser` MCP server |
| `weather_mcp.py` | `milo-weather` MCP server (Open-Meteo) |
| `feed.py` | The X feed and its brief |
| `speech.py` | Speech-to-text and text-to-speech |
| `vault.py`, `permissions.py`, `guard.py` | Saved accounts, approval rules, and the hook that keeps the bridge alive |
| `web/` | The phone app (PWA) |
| `tests/` | pytest suite, and the live behavior suite in `tests/live` |
| `data/` | Your config, token, chats and memory. It is private. |
