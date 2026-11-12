# Milo features

What each part of Milo does, and where it lives in the code. To install, see [INSTALL.md](../INSTALL.md).

## What it does

- **Muse-style layout.** A floating tab bar (hidden while you type), the Milo avatar at the top (tap it to talk), and a "..." menu (new chat, voice mode, Milo's browser, Settings). The side menu (top-left button, or swipe in from the left edge) has the tabs, your chats with search and unread dots, and Settings. With the keyboard up, the message box sits right on the keyboard.
- **Main chat and side chats.** Like Muse, Milo opens on one ongoing main chat. "New chat" starts a side chat for a separate topic. The menu shows Main chat on its own and the side chats below it. To rename a side chat, tap its pencil in the menu or use "Rename chat" in the "..." menu. Milo does not change a name that you set. The main chat cannot be deleted.
- **Goals.** "Tracking" and "Goals" lists, each goal with a status line. Add them yourself or just tell Milo; it adds and updates goals as you talk, and knows them in every chat. Tick a goal off, move it, edit it, or "Talk about it with Milo".
- **Feed.** Three tabs from your X timelines, in the tab bar: Politics and AI (both from For you), and Following (the key posts from people you follow, on any topic). Log in to X once in Milo's browser. Milo reads both timelines there in a tab of its own (it only reads: it never likes, posts or follows), then writes a short brief and picks a few top posts, each with a line on why it matters to you. Every brief line shows the posts behind it, and images are shown only when they carry information (charts, figures, demos). Top posts show as on X, with Open in X and Ask Milo. A video pauses when you scroll past it, leave the Feed or lock the phone; Play on the lock screen goes on with the sound. Photos zoom with a pinch or a double tap. Pull a photo or a sheet down to close it. Political stories stay neutral: the brief says who claims what. Edit sets what should show up in each tab, which tabs to make and how many top posts. A post's "..." menu has Less like this and Mute. Milo reads again every 6 hours in the daytime, or when you tap Refresh. The brief is written by a Claude with no tools at all, so text in a post cannot make it do anything.
- **Ideas** (side menu). Things Milo offers to do ("I can ..."), made from your memory, goals, recent chats and schedule. New ones are made in the background when the list is more than 6 hours old, or when you tap New ideas. "Do it" starts a side chat; "Not now" removes the idea.
- **Attach files.** Tap + to send files or photos with a message. They are saved in `Library/Uploads` on the Mac, and Milo gets their location.
- **Chat and voice.** Type, hold the mic to talk (your words show as you speak; release to send), or tap the orb for hands-free voice mode (it sends when you pause and speaks the reply). Other replies are read aloud only when you tap the speaker button under them (Settings > Speak replies can change this).
- **Background work.** Tasks continue on the Mac after you close the app. You get a push alert when a task is done, but no alerts while the app is open on a screen; they show in the app instead. A long alert comes as one short line (a few words from Haiku, `notice_model`).
- **Auto compact.** Each message re-reads the whole chat, so long chats use up your Claude plan faster. When a chat passes 100k tokens (`compact_at` in `data/config.json`), Milo writes a summary of it and goes on in a fresh session from that summary, like Claude Code's /compact. It is silent: the chat keeps every message and shows no line, brief, size or menu item, and "compact" is an ordinary message. Each run of a scheduled task starts fresh, since its instructions and files carry what it needs.
- **No clear.** The main chat is one long conversation, like talking to a person: there is no way to clear it. Old messages stay; automatic compaction keeps the cost down.
- **Planning.** The milo-planner tools do the parts of planning that must be right every time, in code. `day_view` reads every calendar, the work-meeting feed (`busy_url` in `data/config.json`) and the to-do list for a range of days, and gives the free time and the focus hours left under the rules. `check_plan` checks proposed blocks against the rules in `Instructions/Planning rules.md` (working hours, breaks, nothing in meetings or the hour before a class, a daily cap on planned work, rest and work-only days, class prep size). `workload` compares each to-do's estimate (`est: 3h` on its line) with the free hours before its due date. `plan_block` adds, moves or removes a work block on the calendar and on the to-do's line together. The bridge refuses a calendar change that the user's last message didn't agree to, and every calendar change in a scheduled task's run.
- **Approval cards.** Before Goose changes, sends, or runs something, the phone shows *Allow once / Always allow / Deny*.
- **Memory and persona.** Goose remembers facts that you tell it (Settings > Memory). Memory goes into every chat, so it keeps only short, global facts about you. Rules for one kind of work (job applications, email summaries) go into that work's instruction file: the file a recurring task reads, or `~/Documents/Milo/Instructions/<Topic>.md`. Only the list of those files goes into every chat. You can set its name, tone, and answer length.
- **Upcoming.** Scheduled and recurring tasks that Milo carries out ("every weekday at 8, brief me"). You can create them in chat or with the New button. A task works out of sight, in a hidden chat of its own, and its final message comes to the main chat as Milo's own message (no "ran" line, no steps; weather cards stay), with the alert. You answer it there: the main chat's session gets the messages it has not seen with your next message. A run with nothing new ends with `<quiet/>`: nothing in the chat, no alert and no file. An approval card from a run asks in the main chat. Tap a task in Upcoming to see its runs. Milo knows your list in every chat. Results are also kept in the Library, one folder per task (`Recurring tasks/<title>/`), one file per run.
- **To-dos, not reminders.** Milo has no reminders. "Remind me to X on Y" adds X to `Planner/Tasks.md` in the Library with its due date, like any to-do. The daily "Due today" task (2:30 pm) sends one alert with what is due or overdue, or stays quiet; answer "done with X" in its chat and Milo checks it off.
- **Activity.** A log of each tool call, approval, memory, and schedule.
- **Library.** Files that Milo makes go to `~/Documents/Milo/Library`. It opens on Today: the files added or changed today, from every folder, newest added first (by creation date, not the last change). All files has the folders; Favorites has what you starred. Tap one to see it in the app: photos, videos, PDFs (PDF.js, in `web/vendor`), Markdown, CSV and text. Word, Excel, PowerPoint, Pages and Numbers files show as previews that Quick Look makes on the Mac. Pinch or double-tap to zoom. The share button opens the file in another app (Excel, Word, Files ...). Plots and charts Milo makes for a question go to `~/Documents/Milo/Temp` instead and show right in the chat (tap one to see it full size). They go into the Library only when you ask to keep them, and Temp drops files after 30 days.
- **Hey Siri.** `POST /api/ask` (see Settings > Hey Siri for the Shortcut steps). Siri reads a short spoken answer (Milo's `<say>` part); the chat shows the whole reply, and when it has more detail Siri ends with "The details are in your Milo chat."
- **To-dos and planned work.** `Library/Planner/Tasks.md` holds each to-do's due date and, as `plan: Wed 10-28 15:30-18:30`, the work blocks Milo put on the calendar for it. Milo changes the event and the line together, and "what do I have on Friday" reads the calendars and the list.
- **Browser mode.** Milo has its own Chrome window ("Milo" profile in `data/browser-profile`). Watch it live from the phone (globe button), take control (tap, scroll, type), and give it back. Risky clicks (buy, send, delete, upload) need your OK. Milo hands the browser to you for CAPTCHAs and 2FA.
- **Saved accounts.** Passwords and 2FA secrets live in the macOS Keychain. The bridge types them into the focused field on the matching site only, so the AI never sees them. Each account has an "Ask" switch.
- **Several Google accounts.** Gmail, Calendar and Drive for many accounts through `workspace-mcp` (Settings > Google accounts). Every call names the account. Sign-ins open in Milo's browser.
- **Auto update.** When a file in `web/` changes, the bridge tells each open phone. The app reloads by itself: at once if it is idle, or when you leave it if you are typing, talking, or have a sheet or the browser open. It opens to the same conversation. Changes to the Python files need a restart of `./start.sh`.
- **Permissions tab.** Reading is allowed by default (search mail, read calendars, files and web pages, read-only shell commands, also in loops and pipes). Everything that changes something asks. "Always allow / Always deny" on a card becomes a rule you can change in the tab.

Speech-to-text uses whisper.cpp (large-v3-turbo) on this Mac. Text-to-speech uses Kokoro, a natural neural voice that runs on this Mac (default: Michael, a US male voice; change it in Settings > Voice). The macOS `say` voices are still in the list. Long replies are spoken part by part, so speech starts fast. Goose uses your configured provider (`claude-acp`).

## Files

| Path | Contents |
|---|---|
| `server.py` | Bridge: HTTP API, WebSocket, Siri endpoint |
| `acp.py` | Client for `goose acp` (Agent Client Protocol over stdio) |
| `features.py` | Memory, goals, ideas, activity, library, scheduler, web push |
| `feed.py` | X feed: read the timelines in Milo's Chrome, parse posts, the tool-free brief, `data/feed.json` |
| `speech.py` | whisper-server (STT), Kokoro and `say` (TTS) |
| `browser.py` | Milo's Chrome: launch, live view, remote input, takeover, task lock |
| `browser_mcp.py` | `milo-browser` MCP server: Playwright MCP proxy, risk gate, credential fill |
| `google_mcp.py` | `milo-google` MCP server: several Google accounts through workspace-mcp |
| `mcp_proxy.py` | Shared upstream MCP client and bearer-protected endpoint |
| `vault.py` | Saved accounts (metadata in JSON, secrets in the Keychain) |
| `permissions.py` | Read-only detection, allow/deny/ask rules, and commands that would stop Milo itself |
| `guard.py` | Claude hook: blocks a shell command that kills the bridge Milo runs in |
| `restart.py` | Starts the bridge again after Milo's `<restart/>` |
| `tests/` | pytest suite and a local test website |
| `web/` | The PWA (`web/vendor/pdfjs`: PDF.js for the file viewer) |
| `data/` | Config and access token, conversations, memory, schedules, feed, file previews (private; do not share) |

## Notes

- The bridge listens only on `127.0.0.1`. `tailscale serve` publishes it to your tailnet only.
- The permission mode is set when Goose starts (`GOOSE_MODE`). If you change it in Settings, the bridge restarts Goose.
- To use a new access token, delete `token` from `data/config.json` and restart.
- Milo has its own Claude profile in `data/claude`, so its memory and settings stay apart from your other Claude sessions on the Mac. `./start.sh` asks you to sign in to it once. The sign-in belongs to the folder path: after you move the folder, sign in again.
- Keep the code in `~/Documents/Milo/milo`, not in `~/Documents/Milo` itself. Milo works in `~/Documents/Milo`, and macOS treats `milo` and `Milo` as the same folder.
