"""Milo bridge: a Muse-style phone app (PWA) and Siri endpoint on top of goose (ACP).

Voice in: whisper.cpp on this Mac. Voice out: macOS `say`. Agent: `goose acp` over stdio.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import random
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import keyring
import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from starlette.routing import Route

from acp import GooseAcp
from browser import BrowserError, BrowserManager
from browser_mcp import OLD_OUTPUT, BrowserMCPApp, BrowserTools, pretty_title
from feed import (MOST as FEED_MOST, TABS as FEED_TABS, TIMELINES, Feed, SignedOut, add_linked, brief_prompt, candidates, collect,
                  parse_brief, run_claude, used_ids)
from google_mcp import GoogleMCPApp, GoogleTools
from features import (COMPACT_PROMPT, COMPACTED, GOALS_UPDATE, IDEAS_PROMPT, MEMORY_UPDATE, NOTICE_PROMPT,
                      NOTICE_WORDS, REACT_EVERY, REACT_PROMPT, REACTIONS, RECENT_MAIN, SCHEDULED_RUN, SCHEDULES_UPDATE, TASK_POSTS,
                      TITLE_PROMPT, Activity, Favorites, Goals, Ideas, JsonFile, Library, Memory, Push, Scheduler,
                      build_context, clean_notice, clean_temp, find_picture, clean_reaction, clean_title, extract_directives, extract_goals,
                      extract_quiet, extract_reaction, extract_restart, describe_step, GENERIC_STEPS, extract_say, extract_suggestion, fit_words, parse_ideas, parse_usage, plan_name, react_chance,
                      recent_messages, task_posts, when_label, zip_stream)
from permissions import Permissions, classify
from speech import NeuralVoice, Whisper, speakable, split_speech, synthesize
from vault import Vault
from planner_mcp import BUSY_URL, PlannerMCPApp, PlannerTools
from weather_mcp import WeatherMCPApp, WeatherTools, weather_blocks

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("MILO_DATA_DIR") or ROOT / "data")
DATA.mkdir(parents=True, exist_ok=True)
WEB = Path(os.environ.get("MILO_WEB_DIR") or ROOT / "web")
KEYCHAIN_SERVICE = os.environ.get("MILO_KEYCHAIN_SERVICE", "Milo")
# Milo's own Claude profile (sign-in, memory, settings), apart from the Mac's. start.sh signs in to the same path.
CLAUDE_DIR = Path(os.environ.get("MILO_CLAUDE_DIR") or DATA / "claude").resolve()
CLAUDE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def install_guard() -> None:
    """Milo's Claude runs guard.py before each shell command: it refuses to kill the bridge Milo runs in (Milo
    ended mid-reply and the app stayed down). A hook, as in "Never ask" mode no command reaches on_permission."""
    path = CLAUDE_DIR / "settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    want = {"matcher": "Bash", "hooks": [{"type": "command", "command": f'"{sys.executable}" "{ROOT / "guard.py"}"'}]}
    kept = [m for m in pre if not any("guard.py" in h.get("command", "") for h in m.get("hooks", []))]
    if pre != kept + [want]:
        pre[:] = kept + [want]
        path.write_text(json.dumps(settings, indent=2) + "\n")


install_guard()

# Fewer tokens on every step (measured on Milo's transcripts, 2026-10-20). Each step re-reads the whole context,
# so what sits in it is paid again and again.
TOKEN_SETTINGS = {
    # Claude Code compacts a turn whose context passes this (one turn grew to 437k: 40% of a day's usage was steps
    # over 150k). compact_at does the same between turns.
    "autoCompactWindow": 140_000,
}
# Tools Milo never uses (it has its own scheduled tasks, alerts and chats): their schemas were in every prompt
DENIED_TOOLS = ["CronCreate", "CronDelete", "CronList", "DesignSync", "EnterWorktree", "ExitWorktree", "ListAgents",
                "NotebookEdit", "PushNotification", "RemoteTrigger", "ReportFindings", "ScheduleWakeup"]
# Coding and setup skills, listed in every prompt. Milo keeps the document skills (docx, pdf, pptx, xlsx, docs,
# Google Workspace) and dataviz.
SKILLS_OFF = ["design", "design-sync", "update-config", "verify", "debug", "code-review", "simplify", "batch",
              "fewer-permission-prompts", "doctor", "loop", "schedule", "claude-api", "run", "run-skill-generator",
              "plugin-authoring", "anthropic-skills:import-memory", "anthropic-skills:morning",
              "anthropic-skills:skill-creator"]


def install_token_settings() -> None:
    """Milo's Claude profile gets TOKEN_SETTINGS, DENIED_TOOLS and SKILLS_OFF. Other settings stay as they are."""
    path = CLAUDE_DIR / "settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    want = json.loads(json.dumps(settings))
    want.update(TOKEN_SETTINGS)
    deny = want.setdefault("permissions", {}).setdefault("deny", [])
    deny += [t for t in DENIED_TOOLS if t not in deny]
    want.setdefault("skillOverrides", {}).update({s: "off" for s in SKILLS_OFF})
    if want != settings:
        path.write_text(json.dumps(want, indent=2) + "\n")


install_token_settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")

DEFAULTS = {
    "token": None,
    "port": 8765,
    "goose_cwd": str(Path.home() / "Documents" / "Milo"),   # not home: there Claude loads ~/.claude as project settings
    "library_dir": str(Path.home() / "Documents" / "Milo" / "Library"),
    "whisper_model": str(ROOT / "models" / "ggml-large-v3-turbo-q5_0.bin"),
    "whisper_port": 8178,
    "kokoro_model": str(ROOT / "models" / "kokoro-v1.0.onnx"),
    "kokoro_voices": str(ROOT / "models" / "voices-v1.0.bin"),
    "push_contact": "mailto:milo@example.com",
    "siri_wait_seconds": 60,
    "siri_session_minutes": 15,
    # an auto-approve task runs unattended: a card it raises is denied after this long, so the run goes on
    "unattended_approval_minutes": 10,
    # user-editable in the app
    "assistant_name": "Milo",
    "tone": "warm, plain and direct",
    "length": "short unless the task needs more",
    "voice": "am_michael",
    "voice_rate": 190,
    "permission_mode": "smart_approve",
    "model": "claude-sonnet-5-5",   # Claude model for goose's claude-acp provider
    "title_model": "claude-haiku-5-5",   # chat titles: a few words, no need for the main model
    "notice_model": "claude-haiku-5-5",   # notifications: a long text as one short line
    "reaction_model": "claude-haiku-5-5",   # now and then an emoji on the user's message
    "reactions": True,
    # every step of a turn re-reads the whole session, so a chat this big moves to a fresh session from a summary
    "compact_at": 100_000,   # tokens; Claude Code compacts inside a turn at TOKEN_SETTINGS["autoCompactWindow"]
    # browser mode
    "browser_enabled": True,
    "browser_port": 9333,
    "browser_headless": False,
    "browser_key": None,
}
EDITABLE = {"assistant_name", "tone", "length", "voice", "voice_rate", "permission_mode"}
MODES = {"approve": "Always ask", "smart_approve": "Ask for some actions", "auto": "Never ask"}

VOICE_HINT = (
    "[The request above was spoken on the user's phone. Reply in a few short, natural spoken sentences. "
    "Avoid tables, code blocks and long lists unless asked.]"
)
SEND_TOOLS = {"send_gmail_message"}
ASKS_REACT = re.compile(r"\breact|tap ?back|emoji|\b(?:heart|like|thumbs? ?up)\s+(?:it|this|that|my)\b", re.I)
SAYS_SEND = re.compile(r"\bsend\b", re.I)
NO_SEND = re.compile(r"\b(?:don'?t|do not|never|not yet|no need to|without)\b[^.?!]*\bsend\b", re.I)
# A calendar event changes only when the user's last message agrees or asks for it (their rule of 2026-11-01, broken
# twice the same day: BEHAVIOR #94). "Plan my day" is not a yes: Milo proposes and waits.
CALENDAR_WRITES = {"manage_event", "plan_block"}
SAYS_YES = re.compile(r"\b(?:yes|yeah|yep|yup|ok|okay|sure|go ahead|do it|sounds good|perfect|great|confirm(?:ed)?|"
                      r"please|add|put|schedule|book|block|move|reschedule|shift|push|delete|remove|cancel|drop|"
                      r"create|make it|lock it)\b", re.I)
SAYS_NO = re.compile(r"^\s*no\b|\b(?:don'?t|do not|never|not yet|no need to|wait)\b[^.?!]*\b(?:add|put|schedule|book|"
                     r"block|move|delete|remove|cancel|create|calendar)\b", re.I)
# Siri used to end with "the rest is in the app" while the chat held the same few words (BEHAVIOR #90): now the
# Shortcut reads only the <say> part, the chat shows the whole reply, and the bridge says when the chat has more.
SIRI_HINT = (
    "[The request above came through Siri: the Shortcut reads out loud only the part of your reply inside <say></say>, "
    "with no screen, and the whole reply shows in the user's Milo chat. Check what you would check in the app "
    "(calendars, to-dos) before you answer. Start with <say>one to three short sentences (about 40 words), the answer "
    "first, no lists, links or markdown</say>. After it, add the detail for the chat (times, a list) only when the user "
    "needs more than the spoken part; otherwise write nothing else. Don't say where the rest is: the app adds that.]"
)
SIRI_MORE = "The details are in your Milo chat."
SIRI_MORE_WORDS = 8   # chat text past the spoken part longer than this is detail worth pointing to


def siri_answer(answer: str, said: str) -> str:
    """What the Shortcut reads: the <say> part, and a pointer to the chat when the reply there has more."""
    if not said:
        return speakable(answer, 4000)
    more = len(answer.replace(said, " ").split()) > SIRI_MORE_WORDS
    return speakable(said, 4000) + (f" {SIRI_MORE}" if more else "")

config = JsonFile(DATA / "config.json", {})
CFG = {**DEFAULTS, **config.data}
CFG["token"] = CFG["token"] or secrets.token_urlsafe(24)
CFG["browser_key"] = CFG["browser_key"] or secrets.token_urlsafe(24)
config.data = CFG
config.save()
os.chmod(config.path, 0o600)


# Conversations

STOP_GRACE = 5   # seconds to undo a Stop that would end helper agents
RELEASE_IDLE = 15 * 60   # seconds a side chat waits before its Claude Code process ends (its next message loads it again)


def tool_input(tid: str | None, files: int = 4, tail: int = 600_000) -> tuple[str, dict] | None:
    """A Claude tool call's (name, input), from the newest transcripts in Milo's Claude profile."""
    if not tid or not tid.startswith("toolu_"):
        return None
    needle = f'"id":"{tid}"'.encode()
    logs = sorted((CLAUDE_DIR / "projects").glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:files]
    for f in logs:
        try:
            with open(f, "rb") as fh:
                fh.seek(max(0, f.stat().st_size - tail))
                data = fh.read()
        except OSError:
            continue
        for line in reversed(data.split(b"\n")):
            if needle in line.replace(b'": "', b'":"'):
                try:
                    content = json.loads(line)["message"]["content"]
                except (ValueError, KeyError, TypeError):
                    continue
                for c in content if isinstance(content, list) else []:
                    if c.get("type") == "tool_use" and c.get("id") == tid:
                        return c.get("name", ""), c.get("input") or {}
    return None


class Conversation:
    def __init__(self, id: str, title: str = "New conversation", source: str = "app", messages: list | None = None,
                 created: float | None = None, updated: float | None = None, fixed_title: bool = False,
                 main: bool = False, schedule: str | None = None, sid: str | None = None, used: int = 0,
                 carry: str | None = None, read: float | None = None, inbox: list | None = None):
        self.id = id
        # the goose session: the chat's first one at the start; compacting and each recurring-task run start a new one
        self.sid = sid or id
        self.used = used   # tokens in the session's context, from goose's usage updates
        self.carry = carry   # the summary of a compacted chat, for the new session's first prompt
        self.compacting: asyncio.Task | None = None
        self.main = main   # the one main chat (like Muse); every other chat is a side chat
        # id of the scheduled task this chat runs. Such a chat is hidden: the task works here out of sight, and its
        # reply goes to the main chat as Milo's own message (post_to_main). Its Library folder is the task's title.
        self.schedule = schedule
        self.inbox: list[dict] = inbox or []   # the main chat: task replies posted since its session's last prompt
        self.title = title
        self.source = source
        self.fixed_title = fixed_title
        self.messages: list[dict] = messages or []
        self.created = created or time.time()
        self.updated = updated or self.created
        # the newest `updated` the user has seen on any device: newer means unread (the dot). A chat saved before
        # this was kept counts as read, so no old chat turns unread.
        self.read = self.updated if read is None else read
        self.running = False
        self.replaying = False
        self.queue: list[tuple[str, bool, bool]] = []   # (prompt, voice, a recurring task's run)
        self.stopping = False   # the user pressed Stop on the running turn
        self.halting: asyncio.Task | None = None   # Stop's interrupt of Claude Code; True if it ended the process
        self.pending_stop: asyncio.Task | None = None   # a Stop that can still be undone
        self.ctx: tuple | None = None  # (goose pid, memory, goals, schedules versions) last injected
        self.u16: tuple[dict | None, int] = (None, 0)   # the streaming reply and its length in UTF-16 units
        self.done = asyncio.Event()
        self.since_react = REACT_EVERY - 1   # the user's messages since the last reaction shown
        self.reacting = False   # a reaction call is out for this chat

    def summary(self) -> dict:
        last = next((f"{m['task']} ran" if m.get("task") else m["text"] for m in reversed(self.messages)
                     if m.get("text")), "")
        return {"id": self.id, "title": self.title, "source": self.source, "updated": self.updated,
                "read": self.read, "running": self.running, "queued": len(self.queue), "preview": last[:140], "main": self.main,
                "schedule": self.schedule, "used": self.used, "compacting": bool(self.compacting)}

    def full(self) -> dict:
        return {**self.summary(), "messages": self.messages}

    def to_json(self) -> dict:
        return {"id": self.id, "title": self.title, "source": self.source, "messages": self.messages,
                "created": self.created, "updated": self.updated, "fixed_title": self.fixed_title, "main": self.main,
                "schedule": self.schedule, "sid": self.sid, "used": self.used, "carry": self.carry, "read": self.read,
                "inbox": self.inbox}


class Hub:
    def __init__(self):
        self.store = JsonFile(DATA / "conversations.json", [])
        self.convs: dict[str, Conversation] = {c["id"]: Conversation(**c) for c in self.store.data}
        self.sockets: dict[WebSocket, bool] = {}  # socket -> page visible
        self.heard: dict[WebSocket, float] = {}   # socket -> last message (the app pings every 25 s)
        self.approvals: dict[str, dict] = {}
        self._approval_futures: dict[str, asyncio.Future] = {}
        self.answered: dict[str, dict[str, tuple[str, str]]] = {}   # chat -> command -> (answer, tool call), this turn
        self.side_tasks: set[asyncio.Task] = set()   # waits that outlive a turn, such as approving a task change
        Path(CFG["goose_cwd"]).mkdir(parents=True, exist_ok=True)
        self.goose = GooseAcp(CFG["goose_cwd"], self.on_update, self.on_permission, CFG["permission_mode"],
                              CFG.get("model"), str(CLAUDE_DIR))
        self.whisper = Whisper(Path(CFG["whisper_model"]), CFG["whisper_port"])
        self.neural = NeuralVoice(Path(CFG["kokoro_model"]), Path(CFG["kokoro_voices"]))
        self.memory = Memory(DATA / "memory.md")
        self.goals = Goals(DATA / "goals.json")
        self.ideas = Ideas(DATA / "ideas.json")
        self.ideas_task: asyncio.Task | None = None
        self.feed = Feed(DATA / "feed.json")
        self.feed_task: asyncio.Task | None = None
        self.collect: dict[str, list[str]] = {}   # background sessions (ideas): sid -> reply text
        self.naming: dict[str, str] = {}   # chats Milo is naming: sid -> goose's own title, used if naming fails
        self.activity = Activity(DATA / "activity.json")
        self.library = Library(Path(CFG["library_dir"]))
        # Rules for one kind of work, one file per topic, so memory stays short: only their index goes in every chat
        self.instructions = Path(CFG.get("instructions_dir") or Path(CFG["library_dir"]).parent / "Instructions")
        # Plots Milo shows in a reply, kept out of the Library unless the user asks to save them (BEHAVIOR #76)
        self.temp = Path(CFG.get("temp_dir") or Path(CFG["library_dir"]).parent / "Temp")
        self.temp.mkdir(parents=True, exist_ok=True)
        self.favorites = Favorites(DATA / "favorites.json", self.library)
        self.scheduler = Scheduler(DATA / "schedules.json", self.fire_schedule)
        self.push = Push(DATA, CFG["push_contact"])
        self.siri_wait: dict[str, asyncio.Future] = {}   # chat id -> a Shortcut waiting to speak the answer
        self.notices: set[asyncio.Task] = set()   # notifications waiting for their short line (kept, so they are not lost)
        self.vault = Vault(DATA / "accounts.json", service=KEYCHAIN_SERVICE)
        self.permissions = Permissions(DATA / "permissions.json")
        self.browser = BrowserManager(DATA / "browser-profile", port=CFG["browser_port"],
                                      headless=CFG["browser_headless"], emit=self.on_browser,
                                      working=lambda: any(c.running for c in self.convs.values()) or self.feed_busy)
        self.browser_tools = BrowserTools(self.browser, self.vault, key=CFG["browser_key"],
                                          approve=self.request_approval, record=self.activity.record,
                                          notify=self.notify_browser, conv_for=self.conv_for_key,
                                          files_dir=CFG["library_dir"], output_dir=str(self.temp),
                                          auto_approve=self.auto_approves)
        self.browser_ready = False
        self.google = GoogleTools(DATA, key=CFG["browser_key"], client=google_client, record=self.activity.record)
        self.mcp_keys: dict[str, str] = {}  # per-session key in the MCP URL -> conversation id
        self.google.guard = self.google_guard
        self.weather = WeatherTools(CFG["browser_key"], on_result=self.on_weather)
        # bound late: the live suite swaps google.call for its fake after the Hub is made
        self.planner = PlannerTools(key=CFG["browser_key"], google_call=lambda name, args: self.google.call(name, args),
                                    accounts=lambda: self.google.list_accounts(),
                                    tasks_path=self.library.root / "Planner" / "Tasks.md",
                                    rules_path=self.instructions / "Planning rules.md",
                                    busy_url=CFG.get("busy_url") or BUSY_URL)
        self.planner.guard = self.google_guard
        self.refs: dict[str, str] = {}   # the app's ref of a new chat's first message -> the chat made for it
        self.restarting = False   # Milo asked to restart the bridge: it does once no chat runs

    # browser mode

    def mcp_servers(self) -> tuple[list[dict], str]:
        key = secrets.token_urlsafe(12)
        auth = [{"name": "Authorization", "value": f"Bearer {CFG['browser_key']}"}]
        servers = []
        if CFG["browser_enabled"]:
            servers.append({"type": "http", "name": "milo-browser",
                            "url": f"http://127.0.0.1:{CFG['port']}/mcp/browser?k={key}", "headers": auth})
        if self.google.configured:
            servers.append({"type": "http", "name": "milo-google", "url": f"http://127.0.0.1:{CFG['port']}/mcp/google?k={key}",
                            "headers": auth})
            servers.append({"type": "http", "name": "milo-planner", "url": f"http://127.0.0.1:{CFG['port']}/mcp/planner?k={key}",
                            "headers": auth})
        servers.append({"type": "http", "name": "milo-weather", "url": f"http://127.0.0.1:{CFG['port']}/mcp/weather?k={key}",
                        "headers": auth})
        return servers, key

    def conv_of(self, sid: str) -> Conversation | None:
        """The chat whose current session is sid. Updates from a session a chat has left are dropped."""
        conv = self.convs.get(sid)
        if conv and conv.sid == sid:
            return conv
        return next((c for c in self.convs.values() if c.sid == sid), None)

    def chat_id(self, ref: str | None) -> str | None:
        """The chat an alert is about. ref is a chat's id or a session id (a compacted or cleared chat has a new
        session). A chat's own id wins: it never changes, so a tap always opens that chat. Unknown: no chat."""
        if not ref:
            return None
        conv = self.convs.get(ref) or self.conv_of(ref)
        if conv and conv.schedule and (main := self.main_id()):   # a task's own chat is hidden: its reply is in the main chat
            return main
        return conv.id if conv else None

    def google_guard(self, key: str | None, tool: str, args: dict) -> str | None:
        """An email goes out only after the user says "send" for it (their rule; the prompt alone let "Yeah let's do
        that" send one). A recurring task's run is not checked: the user set its instructions.
        A calendar event (or a work block) changes only when the user's last message agrees or asks for it, and
        never in a scheduled task's run: the run proposes, the user answers in the main chat (BEHAVIOR #94)."""
        if tool in CALENDAR_WRITES and (tool != "manage_event" or str(args.get("action", "")).lower() != "rsvp"):
            return self.calendar_guard(key)
        if tool not in SEND_TOOLS:
            return None
        conv = self.convs.get(self.conv_for_key(key) or "")
        said = next((m for m in reversed(conv.messages) if m["role"] == "user" and not m.get("queued")), None) if conv else None
        if said is None or said.get("scheduled"):
            return None
        text = said.get("text", "")
        if SAYS_SEND.search(text) and not NO_SEND.search(text):
            return None
        log.info("held an email send in %s: the last message doesn't say send", conv.id)
        return ('Not sent. An email goes out only after the user says "send" for it, and their last message did not. '
                'The draft stays saved: show it to them and ask them to say "send".')

    def calendar_guard(self, key: str | None) -> str | None:
        conv = self.convs.get(self.conv_for_key(key) or "")
        said = next((m for m in reversed(conv.messages) if m["role"] == "user" and not m.get("queued")), None) if conv else None
        if said is None:
            return None   # no chat to tell (an unknown key): the prompt's rule is all there is
        if said.get("scheduled"):
            log.info("held a calendar change in a scheduled run (%s)", conv.id)
            return ("Not changed. A scheduled task never changes the calendar. Propose the change in your message; "
                    "the user answers in their main chat.")
        text = said.get("text", "")
        if SAYS_YES.search(text) and not SAYS_NO.search(text):
            return None
        log.info("held a calendar change in %s: the last message doesn't agree to it", conv.id)
        return ("Not changed. A calendar event changes only after the user agrees to that change, and their last "
                "message did not. Propose it (times and what), and ask.")

    def conv_for_key(self, key: str | None) -> str | None:
        if key and key in self.mcp_keys:
            return self.mcp_keys[key]
        # An unknown key: a guess is safe only when one chat runs. With two (a task and the Main chat), the newest
        # one can be the wrong chat, so no chat (an alert then opens the app, not a wrong chat).
        running = [c for c in self.convs.values() if c.running]
        return running[0].id if len(running) == 1 else None

    async def on_weather(self, key: str | None, args: dict, data: dict) -> None:
        """A get_weather result: its data goes on the call's step, and the app shows it as a weather card."""
        cid = self.conv_for_key(key)
        conv = (self.convs.get(cid) or self.conv_of(cid)) if cid else None
        if not conv or not conv.running:
            return
        msg = self._assistant_msg(conv)
        open_ = [t for t in msg["tools"] if t["title"] == "Weather" and "weather" not in t]
        tool = next((t for t in reversed(open_) if t["detail"] == args.get("location")), open_[-1] if open_ else None)
        if tool is None:   # the result came before the step: _tool_event moves the card onto it
            tool = {"id": f"wx-{secrets.token_hex(4)}", "title": "Weather", "status": "completed",
                    "detail": data["location"], "at": len(msg["text"])}
            msg["tools"].append(tool)
        tool["weather"] = data
        await self.broadcast({"t": "tool", "id": conv.id, "tool": tool})

    def auto_approves(self, cid: str | None) -> bool:
        """The chat of a recurring task the user set to auto-approve its browser actions (the job sweep)."""
        conv = self.convs.get(cid or "")
        item = next((i for i in self.scheduler.store.data if conv and conv.schedule == i["id"]), None)
        return bool(item and item.get("auto_approve"))

    async def on_browser(self, state: dict) -> None:
        await self.broadcast({"t": "browser", "state": state})

    async def notify_browser(self, title: str, body: str, conv: str | None) -> None:
        await self.broadcast({"t": "toast", "text": f"{title}: {body}"})
        await self.notify(title, body, conv, tag="browser")

    def save(self) -> None:
        convs = sorted(self.convs.values(), key=lambda c: c.updated, reverse=True)[:300]
        self.store.data = [c.to_json() for c in convs]
        self.store.save()

    # fan-out

    async def broadcast(self, event: dict) -> None:
        for ws in list(self.sockets):
            try:
                await ws.send_json(event)
            except Exception:
                self.sockets.pop(ws, None)
                self.heard.pop(ws, None)

    def someone_looking(self) -> bool:
        """An app window is open on screen. A phone that went away without closing its socket stops counting."""
        now = time.time()
        return any(v and now - self.heard.get(ws, 0) < 60 for ws, v in self.sockets.items())

    async def notify(self, title: str, body: str, conv: str | None = None, tag: str | None = None):
        """Push to the phone only when the app is not open: in the app the same news shows there (cards, toasts, chats).
        A long text goes out as a few words from the cheap model, in the background, so the caller does not wait."""
        if self.someone_looking():
            return
        cid = self.chat_id(conv)
        url = f"/#c={cid}" if cid else "/"
        log.info("push %r -> %s", title, url)   # which chat a tap opens
        if len(body.split()) <= NOTICE_WORDS:
            await self.push.send(title, body, url=url, tag=tag, chat=cid)
            return
        task = asyncio.create_task(self._notice(title, body, url, tag, cid))
        self.notices.add(task)
        task.add_done_callback(self.notices.discard)

    async def _notice(self, title: str, body: str, url: str, tag: str | None, chat: str | None = None) -> None:
        line = ""
        if self.push.subs.data:   # no phone to tell: no model call
            try:
                line = clean_notice(await run_claude(NOTICE_PROMPT.format(title=title, text=body[:4000]),
                                                     CFG["notice_model"], CLAUDE_DIR, timeout=45))
            except Exception:
                log.exception("notification summary failed")
        if not self.someone_looking():   # the app may have opened while the model wrote
            await self.push.send(title, line or fit_words(body, 120), url=url, tag=tag, chat=chat)

    # goose events

    async def on_update(self, sid: str, update: dict) -> None:
        if sid in self.collect:
            if update.get("sessionUpdate") == "agent_message_chunk":
                self.collect[sid].append(update.get("content", {}).get("text", ""))
            return
        conv = self.conv_of(sid)
        if not conv or conv.replaying:
            return
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = update.get("content", {}).get("text", "")
            if text:
                msg = self._assistant_msg(conv)
                # where it goes, in the app's string units (UTF-16): a phone that just read the chat skips what it has
                was, at = conv.u16
                if was is not msg:
                    at = len(msg["text"].encode("utf-16-le")) // 2
                conv.u16 = (msg, at + len(text.encode("utf-16-le")) // 2)
                msg["text"] += text
                await self.broadcast({"t": "chunk", "id": conv.id, "text": text, "at": at})
        elif kind == "agent_thought_chunk":
            await self.broadcast({"t": "thinking", "id": conv.id})
        elif kind in ("tool_call", "tool_call_update"):
            await self._tool_event(conv, update)
        elif kind == "usage_update" and update.get("used"):   # a turn starts with used 0: keep the last size
            conv.used = int(update["used"])
        elif kind == "session_info_update" and update.get("title") and not conv.fixed_title and conv.sid == conv.id:
            if conv.id in self.naming:
                self.naming[conv.id] = update["title"]
                return
            conv.title = update["title"]
            await self.broadcast({"t": "title", "id": conv.id, "title": conv.title})

    async def _tool_event(self, conv: Conversation, update: dict) -> None:
        msg = self._assistant_msg(conv)
        tid = update.get("toolCallId")
        tool = next((t for t in msg["tools"] if t["id"] == tid), None)
        event = {"t": "tool", "id": conv.id}
        if tool is None:
            tool = {"id": tid, "title": "Working", "status": "pending", "detail": "", "at": len(msg["text"])}
            msg["tools"].append(tool)
        if update.get("title"):
            tool["title"] = pretty_title(update["title"])
            if tool["title"].startswith("Browser:"):
                tool["browser"] = True
            if tool["title"].startswith("mcp: milo-weather"):
                tool["title"] = "Weather"
                early = next((t for t in msg["tools"] if t["id"].startswith("wx-")), None)
                if early and "weather" not in tool:   # the card came first: one step, not two
                    tool["weather"] = early["weather"]
                    msg["tools"].remove(early)
                    event["replaces"] = early["id"]
        if update.get("status"):
            tool["status"] = update["status"]
        raw = update.get("rawInput") or {}
        detail = raw.get("command") or raw.get("description") or raw.get("url") or raw.get("file_path") or ""
        if tool["title"] == "Weather":   # its result is the forecast's JSON: the place says more
            detail = raw.get("location") or ""
        if not detail and tool["title"] != "Weather":
            for c in update.get("content") or []:
                text = (c.get("content") or {}).get("text", "")
                if text and not text.startswith("```"):
                    detail = text
                    break
        if detail and not tool["detail"]:
            tool["detail"] = detail[:300]
        if tool["status"] in ("completed", "failed") and tool["title"] in GENERIC_STEPS and not tool.get("named"):
            # goose passes Claude's Bash, Read and Edit steps without their input: Claude's own log has it
            found = await asyncio.to_thread(tool_input, tid)
            if found:
                title, more = describe_step(*found)
                if title:
                    tool["title"], tool["detail"], tool["named"] = title, (more or tool["detail"])[:300], True
        self.activity.record("tool", tool["title"], conv.id, tool["status"], tool["detail"], key=tid)
        await self.broadcast(event | {"tool": tool})

    async def on_permission(self, sid: str, tool_call: dict, options: list[dict]) -> str | None:
        ids = [o["optionId"] for o in options]
        allow = "allow_once" if "allow_once" in ids else next((o for o in ids if o.startswith("allow")), None)
        deny = "reject_once" if "reject_once" in ids else next((o for o in ids if o.startswith("reject")), None)
        if sid in self.collect:
            return deny   # background prompts (a compact summary) do not use tools
        conv = self.conv_of(sid)
        sid = conv.id if conv else sid   # approvals and the Activity log name the chat, not its session
        if (tool_call.get("title") or "").startswith("mcp: milo-browser") and allow:
            return allow  # the browser server asks the user itself, for the risky actions only
        raw = tool_call.get("rawInput") or {}
        info = classify(tool_call.get("title", ""), raw)
        self.permissions.seen(info)
        decision = self.permissions.decide(info, CFG["permission_mode"])
        if decision == "allow" and allow:
            return allow
        if decision == "deny" and deny:
            self.activity.record("approval", f"Blocked by your rule: {info['label']}", sid, "denied",
                                 raw.get("command", ""))
            return deny
        texts = [(c.get("content") or {}).get("text", "") for c in tool_call.get("content") or []]
        title = texts[0] if texts and texts[0] else pretty_title(tool_call.get("title", "Run a tool"))
        command = (raw.get("command") or json.dumps(raw, indent=1)[:800]) if raw else ""
        if info.get("always_ask"):
            ids = [o for o in ids if o != "allow_always"]   # sending email asks every time
        elif command and (prev := self.answered.get(sid, {}).get(command)):
            # when a turn ends, the commands it asked about come again (they don't run); the user already answered
            log.info("repeat permission request in %s: %s (first %s)", sid, tool_call.get("toolCallId"), prev[1])
            return prev[0]
        choice = await self.request_approval(sid, title, command, ids, rule_key=info["key"])
        # "Always" answers become Milo rules (visible in the Permissions tab); Claude Code only gets a one-off answer
        if choice == "allow_always":
            for key in info.get("keys") or [info["key"]]:   # each command of a shell chain gets the rule
                self.permissions.set_rule(key, "allow")
            choice = allow
        elif choice == "reject_always":
            for key in info.get("keys") or [info["key"]]:
                self.permissions.set_rule(key, "deny")
            choice = deny
        if command and choice and not info.get("always_ask"):
            self.answered.setdefault(sid, {})[command] = (choice, tool_call.get("toolCallId") or "")
        return choice

    async def request_approval(self, sid: str | None, title: str, detail: str, options: list[str],
                               rule_key: str | None = None) -> str | None:
        """Show an approval card (and push an alert); return the option the user picked, or None if cancelled."""
        conv = self.convs.get(sid or "")
        approval = {"id": uuid.uuid4().hex[:10], "conv": sid, "ts": time.time(), "title": title[:160],
                    "command": detail, "options": options, "rule": rule_key}
        fut = asyncio.get_running_loop().create_future()
        self.approvals[approval["id"]] = approval
        self._approval_futures[approval["id"]] = fut
        self.activity.record("approval", approval["title"], sid, "waiting", detail, key=approval["id"])
        await self.broadcast({"t": "approval", "approval": approval})
        await self.notify("Needs your OK", approval["title"], sid, tag=approval["id"])   # iOS adds "from Milo"
        if conv and conv.source == "siri":
            conv.done.set()  # let a waiting Siri request answer "check the app"
        try:
            if not self.auto_approves(sid):
                return await fut
            try:   # a sweep that waited on a card stalled for hours
                return await asyncio.wait_for(fut, CFG["unattended_approval_minutes"] * 60)
            except asyncio.TimeoutError:
                self.activity.record("approval", approval["title"], sid, "denied (no answer)", key=approval["id"])
                await self.broadcast({"t": "approval_done", "id": approval["id"], "conv": sid,
                                      "decision": "denied (no answer)"})
                return next((o for o in options if o.startswith("reject")), None)
        finally:
            self.approvals.pop(approval["id"], None)
            self._approval_futures.pop(approval["id"], None)

    async def resolve_approval(self, aid: str, option: str | None) -> None:
        approval, fut = self.approvals.get(aid), self._approval_futures.get(aid)
        if not approval or not fut or fut.done():
            raise HTTPException(404, "approval no longer pending")
        if option is not None and option not in approval["options"]:
            raise HTTPException(400, "unknown option")
        fut.set_result(option)
        label = {"allow_once": "allowed once", "allow_always": "always allowed", "allow_site": "allowed on this site",
                 "reject_once": "denied", "reject_always": "always denied"}.get(option or "", "cancelled")
        self.activity.record("approval", approval["title"], approval["conv"], label, key=aid)
        await self.broadcast({"t": "approval_done", "id": aid, "conv": approval["conv"], "decision": label})

    async def drop_approvals(self, sid: str | None = None) -> None:
        for aid, fut in list(self._approval_futures.items()):
            approval = self.approvals.get(aid, {})
            if (sid is None or approval.get("conv") == sid) and not fut.done():
                fut.set_result(None)
                # the app removes the card only on approval_done: without it a card stayed after Stop or a delete
                self.activity.record("approval", approval.get("title", ""), approval.get("conv"), "cancelled", key=aid)
                await self.broadcast({"t": "approval_done", "id": aid, "conv": approval.get("conv"), "decision": "cancelled"})

    @staticmethod
    def _assistant_msg(conv: Conversation) -> dict:
        """The running turn's reply. It stays one message: a message queued while it streams waits below it (the next
        turn gets its own reply). The app places it the same way."""
        m = conv.messages
        at = next((i for i, x in enumerate(m) if x["role"] == "user" and x.get("queued")), len(m))
        if at and m[at - 1]["role"] == "assistant":
            return m[at - 1]
        m.insert(at, {"role": "assistant", "text": "", "tools": [], "notes": [], "ts": time.time()})
        return m[at]

    # prompts

    async def new_conversation(self, source: str = "app", title: str | None = None,
                               schedule: str | None = None) -> Conversation:
        servers, key = self.mcp_servers()
        sid = await self.goose.new_session(servers)
        self.mcp_keys[key] = sid
        conv = Conversation(sid, source=source, title=title or "New conversation", fixed_title=bool(title),
                            schedule=schedule)
        self.convs[sid] = conv
        self.save()
        await self.broadcast({"t": "conv", "conv": conv.summary()})
        return conv

    def main_id(self) -> str | None:
        return next((c.id for c in self.convs.values() if c.main), None)

    async def main_conv(self) -> Conversation:
        """The main chat. It is made on the first message sent to it."""
        if cid := self.main_id():
            return self.convs[cid]
        conv = await self.new_conversation(title="Main chat")
        conv.main = True
        self.save()
        await self.broadcast({"t": "conv", "conv": conv.summary()})
        return conv

    async def submit(self, conv: Conversation, text: str, voice: bool, scheduled: bool = False,
                     run: str | None = None) -> None:
        if not text:
            raise HTTPException(400, "empty message")
        queued = conv.running
        task = scheduled and bool(conv.schedule)   # a run of a scheduled task, in its hidden chat
        if not conv.messages and not conv.fixed_title:
            self.naming[conv.id] = ""
            asyncio.create_task(self._name_chat(conv, text))
        msg = {"role": "user", "text": text, "voice": voice, "ts": time.time(), "queued": queued,
               **({"scheduled": True, "task": self.schedule_title(conv)} if scheduled else {}),
               **({"run": run} if run else {})}
        if run and queued:
            self.scheduler.update_run(run, "queued")
        conv.messages.append(msg)
        conv.updated = time.time()
        await self.broadcast({"t": "user", "id": conv.id, "text": text, "voice": voice, "queued": queued,
                              "scheduled": scheduled, "task": msg.get("task"), "ts": msg["ts"]})
        if not scheduled:
            self.maybe_react(conv, msg)
        prompt = SCHEDULED_RUN.format(text=text, title=msg["task"]) if scheduled else text
        main = self.convs.get(self.main_id() or "")
        if scheduled and main and main is not conv:
            day = [m for m in main.messages if m.get("text") and m.get("ts", 0) > time.time() - 86400]
            if day:
                prompt += "\n\n" + RECENT_MAIN.format(recent=recent_messages(day, n=8, cap=400))
        if queued:
            conv.queue.append((prompt, voice, task))
        else:
            conv.running = True
            conv.done.clear()
            asyncio.create_task(self._run(conv, prompt, voice, task))
        await self.broadcast({"t": "conv", "conv": conv.summary()})

    def _prompt_blocks(self, conv: Conversation, text: str, voice: bool) -> list[dict]:
        # The user's words go first: goose titles a session from the start of its first prompt.
        pid = self.goose.proc.pid if self.goose.proc else 0
        parts = [text]
        if voice:   # a Siri Shortcut waiting for this turn speaks the reply itself
            parts.append(SIRI_HINT if conv.id in self.siri_wait else VOICE_HINT)
        if conv.ctx is None or conv.ctx[0] != pid:
            parts.append(build_context(CFG, self.memory.read(), self.library.root, browser=self.browser_ready,
                                       extra=self.google.context(), goals=self.goals.context(),
                                       schedules=self.scheduler.context(), instructions=self.instructions,
                                       temp=self.temp))
            if conv.carry:
                parts.append(conv.carry)
                conv.carry = None
        else:
            if conv.ctx[1] != self.memory.version:
                parts.append(MEMORY_UPDATE.format(memory=self.memory.read() or "(empty)"))
            if conv.ctx[2:3] != (self.goals.version,):
                parts.append(GOALS_UPDATE.format(goals=self.goals.context() or "(none)"))
            if conv.ctx[3:] != (self.scheduler.version,):
                parts.append(SCHEDULES_UPDATE.format(schedules=self.scheduler.context() or "(none)"))
        conv.ctx = (pid, self.memory.version, self.goals.version, self.scheduler.version)
        if conv.inbox:   # what Milo posted here from scheduled tasks: the user may answer one of them now
            parts.append(TASK_POSTS.format(posts=task_posts(conv.inbox)))
            conv.inbox = []
        return [{"type": "text", "text": "\n\n".join(parts)}]

    async def _run(self, conv: Conversation, text: str, voice: bool, task: bool = False) -> None:
        while True:
            stop, error = "end_turn", None
            try:
                await self.goose.ensure_running()
                if conv.compacting:   # a message sent while the chat moves to its new session goes there
                    await conv.compacting
                # each run of a recurring task starts a new session: its instructions and files carry over, not old runs
                if task and any(m["role"] == "assistant" for m in conv.messages):
                    await self._new_session(conv)
                if conv.halting:
                    halted, conv.halting = await conv.halting, None
                    if halted and self.goose.is_loaded(conv.sid):   # a goose started since resumes it anyway
                        try:   # its Claude Code process has ended: go on in a fork, which keeps the history
                            await self._fork_session(conv)
                        except Exception:
                            log.exception("fork failed")
                            await self._new_session(conv)
                if not self.goose.is_loaded(conv.sid):
                    servers, key = self.mcp_servers()
                    self.mcp_keys[key] = conv.id
                    conv.replaying = True
                    try:
                        await self.goose.load_session(conv.sid, servers)
                    finally:
                        conv.replaying = False
                self.answered.pop(conv.id, None)
                result = await self.goose.prompt(conv.sid, self._prompt_blocks(conv, text, voice))
                stop = (result or {}).get("stopReason", "end_turn")
                conv.used = ((result or {}).get("usage") or {}).get("totalTokens") or conv.used
                if stop == "cancelled" and not conv.stopping:
                    stop = "end_turn"   # goose reports many finished tool turns as cancelled; only Stop counts
            except Exception as e:  # keep the bridge alive whatever goose does
                log.exception("prompt failed")
                error = str(e) or e.__class__.__name__
            await self._finish(conv, stop, error, voice)
            conv.stopping = False
            if not conv.queue:
                for m in conv.messages:   # Stop dropped the queue: those messages won't run (the app shows them as sent)
                    m.pop("queued", None)
                break
            text, voice, task = conv.queue.pop(0)
            nxt = next((m for m in conv.messages if m.get("queued")), None)   # the queue keeps message order
            if nxt:
                del nxt["queued"]
                if nxt.get("run"):
                    self.scheduler.update_run(nxt["run"], "running")
            await self.broadcast({"t": "conv", "conv": conv.summary()})
        conv.running = False
        conv.done.set()
        await self.browser.release_lock(conv.id)
        self.browser_tools.forget_task(conv.id)
        if self.convs.get(conv.id) is not conv:   # deleted while it ran: a "conv" event would bring it back in the app
            return
        # not after a task run: the next run starts fresh anyway
        if conv.used >= CFG["compact_at"] and not error and not task and not conv.compacting:
            conv.compacting = asyncio.create_task(self.compact(conv))
        self.save()
        await self.broadcast({"t": "conv", "conv": conv.summary()})

    async def _finish(self, conv: Conversation, stop: str, error: str | None, voice: bool) -> None:
        msg = self._assistant_msg(conv)
        msg["text"], msg["suggest"] = extract_suggestion(msg["text"])
        # tags in a <schedule> are part of the task's text (a task's "add <quiet/>"): take the schedules out first
        msg["text"], facts, schedules = extract_directives(msg["text"])
        msg["text"], quiet = extract_quiet(msg["text"])
        msg["text"], restart = extract_restart(msg["text"])
        msg["text"], goal_changes = extract_goals(msg["text"])
        msg["text"], reaction = extract_reaction(msg["text"])
        msg["text"], said = extract_say(msg["text"])
        asked = next((m for m in reversed(conv.messages) if m["role"] == "user" and not m.get("queued")), {})
        if reaction and not ASKS_REACT.search(asked.get("text", "")):   # "Do not react unless the user asks"
            reaction = None
        if reaction:   # the user asked Milo to react: on the message this turn answers, or one before it
            said = [m for m in conv.messages[:conv.messages.index(asked) + 1] if m["role"] == "user" and not m.get("scheduled")] if asked else []
            emoji, back = reaction
            if said:
                target = said[-1 - min(back, len(said) - 1)]
                target["reaction"] = emoji
                await self.broadcast({"t": "reaction", "id": conv.id, "ts": target["ts"], "emoji": emoji})
        for change in goal_changes:
            note = self.apply_goal(change, conv.id)
            if note:
                msg["notes"].append(note)
        if goal_changes:
            await self.broadcast({"t": "goals"})
        for fact in facts:
            self.memory.add(fact)
            msg["notes"].append({"kind": "memory", "text": fact})
            self.activity.record("memory", f"Remembered: {fact}", conv.id, "saved")
        for s in schedules:
            changes = {k: s[k] for k in ("when", "cron", "title", "text") if k in s}
            if "id" in s and changes:   # a new time, title or instruction waits for the user's OK
                item = self.scheduler.get(s["id"])
                note = {"kind": "schedule" if item else "error",
                        "text": f"Asked you to approve a change to {item['title']}" if item
                        else "Could not find that scheduled item"}
                msg["notes"].append(note)
                if item:
                    task = asyncio.create_task(self.confirm_schedule_edit(conv.id, item, changes, note))
                    self.side_tasks.add(task)
                    task.add_done_callback(self.side_tasks.discard)
            if "id" in s and "enabled" not in s:
                continue
            if "id" in s and asked.get("scheduled"):
                # the switch is the user's latest choice: a scheduled run never turns a task on or off
                self.activity.record("schedule", "Ignored a scheduled run's pause or resume", conv.id, "ignored")
                continue
            if "id" in s:   # paused or resumed from the chat: the same switch as in the Upcoming tab
                item = self.scheduler.toggle(s["id"], s["enabled"])
                if not item:
                    msg["notes"].append({"kind": "error", "text": "Could not find that scheduled item"})
                    continue
                done = "Resumed" if s["enabled"] else "Paused"
                msg["notes"].append({"kind": "schedule", "text": f"{done} {item['title']}", "next": item["next"],
                                     "cron": item["cron"]})
                self.activity.record("schedule", f"{done}: {item['title']}", conv.id, done.lower())
                continue
            try:
                item = self.scheduler.add(title=s["title"], text=s["text"], when=s["when"], cron=s["cron"],
                                          source_conv=conv.id)
                msg["notes"].append({"kind": "schedule", "text": s["title"], "next": item["next"], "cron": s["cron"]})
                self.activity.record("schedule", f"Scheduled: {s['title']}", conv.id, "created")
            except ValueError as e:
                msg["notes"].append({"kind": "error", "text": f"Could not schedule '{s['title']}': {e}"})
        if schedules:
            await self.broadcast({"t": "schedules"})
        if error:
            msg["error"] = error
        elif stop == "cancelled":
            msg["notes"].append({"kind": "stopped", "text": "Stopped"})
        posts = bool(conv.schedule and asked.get("scheduled") and msg["text"] and not error and stop != "cancelled"
                     and not quiet)
        if posts:
            # the weather cards go in the file too: the Library shows a ```weather block as the same card
            p = self.library.save_result(self.schedule_title(conv), weather_blocks(msg) + msg["text"], asked["ts"])
            msg["notes"].append({"kind": "saved", "text": str(p.parent.relative_to(self.library.root))})
        # the answer: the text after the last tool call (before it, Milo narrates its steps)
        answer = msg["text"][max((t.get("at", 0) for t in msg.get("tools", [])), default=0):].strip() or msg["text"]
        if asked.get("run"):
            status = "error" if error else "stopped" if stop == "cancelled" else "quiet" if quiet else "done"
            self.scheduler.update_run(asked["run"], status, error or answer)
            await self.broadcast({"t": "schedules"})
        conv.updated = time.time()
        self.save()
        # queued: messages still waiting; the first runs next, and none means Stop dropped them
        await self.broadcast({"t": "done", "id": conv.id, "stop": stop, "error": error, "voice": voice, "message": msg,
                              "queued": len(conv.queue)})
        waiter = self.siri_wait.pop(conv.id, None)   # the Shortcut speaks it: no push
        silent = bool(waiter and not waiter.done() and not asked.get("scheduled"))
        if silent:
            waiter.set_result(siri_answer(answer, said) or ("Sorry, that failed." if error else "Done."))
        if posts:   # in the background: it waits for the main chat's running turn, and the next run must not wait
            item = self.scheduler.get(conv.schedule) or {}
            task = asyncio.create_task(self.post_to_main(self.schedule_title(conv), msg, answer, item.get("text", "")))
            self.side_tasks.add(task)
            task.add_done_callback(self.side_tasks.discard)
        elif conv.schedule and asked.get("scheduled"):
            pass   # quiet, failed or stopped: the main chat shows nothing, the run's history in Upcoming says it
        elif not silent and not error and stop != "cancelled" and not (quiet and asked.get("scheduled")):
            await self.notify(conv.title, speakable(answer, 4000) or "Done.", conv.id)   # the whole answer, for the summary
        if restart and not error and stop != "cancelled" and not asked.get("scheduled"):
            self.restart_soon(conv.id)

    async def post_to_main(self, title: str, msg: dict, answer: str, instruction: str = "") -> None:
        """A scheduled task's reply, as Milo's own message in the main chat, like a person texting you: no "ran" line, no
        steps, only the answer (and its weather cards). The task worked in its hidden chat. The main session hears
        about the message with the user's next prompt (TASK_POSTS), so a reply to it goes on from there."""
        main = await self.main_conv()
        while main.running:   # never between the user's message and its reply
            await main.done.wait()
        post = {"role": "assistant", "text": answer, "tools": [t for t in msg.get("tools", []) if t.get("weather")],
                "notes": [], "ts": time.time(), "from_task": title}
        if msg.get("suggest"):
            post["suggest"] = msg["suggest"]
        main.messages.append(post)
        # the task's instruction comes along: the user's answer here finishes the task (log it, update the list)
        main.inbox.append({"task": title, "ts": post["ts"], "text": answer, "instruction": instruction})
        main.updated = time.time()
        self.save()
        await self.broadcast({"t": "message", "id": main.id, "message": post})
        await self.broadcast({"t": "conv", "conv": main.summary()})
        await self.notify(title, speakable(answer, 4000) or "Done.", main.id)

    def restart_soon(self, cid: str) -> None:
        """Milo asked (<restart/>) to restart the bridge it runs in. A shell command can't: killing the bridge
        ends Milo mid-turn, so nothing starts it again. Here a detached helper starts a new bridge once this one
        has exited, after the running chats and alerts finish."""
        if self.restarting:
            return
        self.restarting = True
        self.activity.record("restart", "Restarting Milo", cid, "waiting")
        task = asyncio.create_task(self._restart_when_idle())
        self.side_tasks.add(task)
        task.add_done_callback(self.side_tasks.discard)

    async def _restart_when_idle(self) -> None:
        while any(c.running or c.compacting for c in self.convs.values()) or self.notices:
            await asyncio.sleep(1)
        self.save()
        log.info("restarting at Milo's request")
        subprocess.Popen([sys.executable, str(ROOT / "restart.py"), str(os.getpid())], cwd=ROOT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        os.kill(os.getpid(), signal.SIGTERM)   # uvicorn stops as on Ctrl-C: goose, Whisper and the MCP servers too

    async def confirm_schedule_edit(self, cid: str, item: dict, changes: dict, note: dict) -> None:
        """Milo's change to a scheduled task applies only after the user allows it on an approval card."""
        title, lines = item["title"], []
        if changes.keys() & {"when", "cron"}:
            lines.append(f"When: {when_label(item['when'], item['cron'])} → "
                         f"{when_label(changes.get('when'), changes.get('cron'))}")
        if "title" in changes:
            lines.append(f"Title: {title} → {changes['title']}")
        if "text" in changes:
            lines.append(f"Instruction: {changes['text']}")
        choice = await self.request_approval(cid, f"Change {title}?", "\n".join(lines), ["allow_once", "reject_once"])
        if choice == "allow_once":
            try:
                self.scheduler.edit(item["id"], **changes)
                note["text"] = f"Changed {title}"
                self.activity.record("schedule", f"Changed: {title}", cid, "changed", "\n".join(lines))
            except ValueError as e:
                note.update(kind="error", text=f"Could not change {title}: {e}")
        else:
            note["text"] = f"Did not change {title}"
        self.save()
        await self.broadcast({"t": "schedules"})

    def apply_goal(self, change: dict, conv: str | None) -> dict | None:
        """A <goal> tag from Milo: add a goal or update one. Returns a note for the reply."""
        try:
            if "title" in change:
                g = self.goals.add(change["title"], change.get("note", ""), change.get("section", "goal"))
                text = f"New goal: {g['title']}" if g["section"] == "goal" else f"Tracking: {g['title']}"
            else:
                g = self.goals.update(change["id"], note=change.get("note") or None, done=change.get("done"))
                text = f"Goal reached: {g['title']}" if change.get("done") else f"Goal updated: {g['title']}"
        except (KeyError, ValueError) as e:
            log.warning("goal change ignored: %s (%s)", change, e)
            return None
        self.activity.record("goal", text, conv, "saved", g.get("note", ""))
        return {"kind": "goal", "text": text}

    async def _new_session(self, conv: Conversation, carry: str | None = None) -> None:
        """Move a chat to a new goose session. The app keeps its messages; Claude starts from the context (and carry)."""
        servers, key = self.mcp_servers()
        sid = await self.goose.new_session(servers)
        self.mcp_keys[key] = conv.id
        conv.sid, conv.used, conv.ctx, conv.carry = sid, 0, None, carry
        self.save()

    async def release_sessions(self) -> None:
        """Close the goose sessions that won't be prompted soon, with their Claude Code processes: old sessions (the
        chat compacted, a task ran again, the chat was deleted) and side chats quiet for RELEASE_IDLE. The main chat
        stays loaded, so it answers at once."""
        for sid in self.goose.loaded():
            conv = next((c for c in self.convs.values() if c.sid == sid), None)
            if conv and (conv.main or conv.running or conv.compacting or time.time() - conv.updated < RELEASE_IDLE):
                continue
            try:
                await self.goose.close_session(sid)
            except Exception:
                log.exception("closing session %s failed", sid)

    async def close_tabs(self) -> None:
        """Milo is idle and the user isn't driving the browser: close the tabs Milo opened while it worked."""
        b = self.browser
        if not b.browser or not b.browser.is_connected() or b.lock_owner or b.controller != "milo" or b.working():
            return
        if n := await b.close_milos_tabs():
            log.info("closed %d tab(s) Milo opened", n)
            await self.browser_tools.select_shown()

    async def _fork_session(self, conv: Conversation) -> None:
        """Move a chat to a copy of its goose session. Claude keeps the whole conversation."""
        servers, key = self.mcp_servers()
        sid = await self.goose.fork_session(conv.sid, servers)
        self.mcp_keys[key] = conv.id
        conv.sid = sid
        self.save()

    def _running_agents(self, conv: Conversation) -> int:
        """Subagents (Claude's Task tool) still running in the reply of the turn in progress."""
        for m in reversed(conv.messages):
            if m["role"] == "assistant":
                return sum(t.get("title") in ("Task", "Agent") and t.get("status") in ("pending", "in_progress")
                           for t in m.get("tools") or [])
            if not m.get("queued"):   # the turn has no reply yet
                return 0
        return 0

    async def _halt(self, sid: str, agents: int) -> bool:
        try:
            halted = await self.goose.interrupt(sid)
        except Exception:
            log.exception("interrupt failed")
            halted = False
        if agents:   # say so: an agent works out of sight, and Stop used to leave it running
            them = f"{agents} helper agent{'s' if agents > 1 else ''}"
            await self.broadcast({"t": "toast", "stop": True, "text": f"Stopped Milo and {them}" if halted
                                  else f"Couldn't stop {them} on your Mac"})
        return halted

    async def compact(self, conv: Conversation) -> bool:
        """Like Claude Code's /compact: the long session writes a summary, and a new session starts from it. It is
        silent: the chat keeps its messages and shows nothing (the user talks to Milo, not to a session)."""
        before = conv.used
        try:
            await self.goose.ensure_running()
            if not self.goose.is_loaded(conv.sid):   # its replayed history must not end up in the summary
                conv.replaying = True
                try:
                    await self.goose.load_session(conv.sid)
                finally:
                    conv.replaying = False
            self.collect[conv.sid] = []
            try:
                await self.goose.prompt(conv.sid, [{"type": "text", "text": COMPACT_PROMPT}])
                summary = "".join(self.collect[conv.sid]).strip()
            finally:
                self.collect.pop(conv.sid, None)
            if not summary:
                log.warning("compact: no summary for %s", conv.id)
                return False
            await self._new_session(conv, COMPACTED.format(summary=summary, recent=recent_messages(conv.messages)))
        except Exception:
            log.exception("compact failed")
            return False
        finally:
            conv.compacting = None
        size = f" from {round(before / 1000)}k tokens" if before else ""
        self.activity.record("compact", f"Compacted {conv.title}", conv.id, "done", size.strip())
        self.save()
        await self.broadcast({"t": "conv", "conv": conv.summary()})
        return True

    def maybe_react(self, conv: Conversation, msg: dict) -> None:
        """Now and then an emoji on the user's message. A local check picks the few that get a call to the cheap model,
        and only while the app is on screen (Siri shows no bubbles)."""
        conv.since_react += 1
        if not CFG["reactions"] or conv.reacting or not self.someone_looking():
            return
        if random.random() >= react_chance(msg["text"], conv.since_react):
            return
        conv.reacting = True
        task = asyncio.create_task(self._react(conv, msg))
        self.side_tasks.add(task)
        task.add_done_callback(self.side_tasks.discard)

    async def _react(self, conv: Conversation, msg: dict) -> None:
        """Only a reaction the user sees starts the pause: a "none" on a plain message must not hide the next one
        ("I love you" got nothing after a task message was checked)."""
        try:
            said = await run_claude(REACT_PROMPT.format(choices=" ".join(REACTIONS), text=msg["text"][:1500]),
                                    CFG["reaction_model"], CLAUDE_DIR, timeout=30)
        except Exception:
            log.exception("reaction failed")
            return
        finally:
            conv.reacting = False
        emoji = clean_reaction(said)
        log.info("reaction in %s: %s", conv.id, emoji or "none")
        if not emoji or conv.id not in self.convs or not any(m is msg for m in conv.messages):
            return
        conv.since_react = 0
        msg["reaction"] = emoji
        self.save()
        await self.broadcast({"t": "reaction", "id": conv.id, "ts": msg["ts"], "emoji": emoji})

    async def _name_chat(self, conv: Conversation, text: str) -> None:
        """Name a chat from its first message (goose would use the first few words)."""
        title = ""
        try:
            title = clean_title(await run_claude(TITLE_PROMPT.format(text=text[:2000]), CFG["title_model"], CLAUDE_DIR,
                                                 timeout=60))
        except Exception:
            log.exception("chat title failed")
        fallback = self.naming.pop(conv.id, "")
        if conv.fixed_title or conv.id not in self.convs or not (title or fallback):
            return
        conv.title, conv.fixed_title = title or fallback, bool(title)
        self.save()
        await self.broadcast({"t": "title", "id": conv.id, "title": conv.title})

    # ideas: things Milo offers to do, made in a background session without tools

    def refresh_ideas(self) -> None:
        if not (self.ideas_task and not self.ideas_task.done()):
            self.ideas_task = asyncio.create_task(self._make_ideas())

    @property
    def ideas_busy(self) -> bool:
        return bool(self.ideas_task and not self.ideas_task.done())

    async def _make_ideas(self) -> None:
        await self.broadcast({"t": "ideas", "busy": True})
        try:
            recent = sorted(self.convs.values(), key=lambda c: c.updated, reverse=True)[:12]
            chats = "\n".join(f"- {c.title}: {c.summary()['preview'][:160]}" for c in recent) or "(none)"
            upcoming = "\n".join(f"- {s['title']}" for s in self.scheduler.upcoming()[:10]) or "(none)"
            prompt = IDEAS_PROMPT.format(memory=self.memory.read() or "(nothing yet)", goals=self.goals.context() or "(none)",
                                         chats=chats, schedules=upcoming, n=5,
                                         today=time.strftime("%A %Y-%m-%d %H:%M"))
            items = parse_ideas(await run_claude(prompt, CFG.get("model"), CLAUDE_DIR))
            if items:
                self.ideas.replace(items)
            else:
                log.warning("ideas: no ideas in the reply")
        except Exception:
            log.exception("ideas failed")
        finally:
            await self.broadcast({"t": "ideas", "busy": False})

    # feed: AI and political news from the user's X timelines, read in Milo's browser and summed up by a Claude without tools

    def refresh_feed(self) -> None:
        if not self.feed_busy:
            self.feed_task = asyncio.create_task(self._make_feed())

    @property
    def feed_busy(self) -> bool:
        return bool(self.feed_task and not self.feed_task.done())

    async def _make_feed(self) -> None:
        await self.broadcast({"t": "feed", "busy": True})
        try:
            settings = self.feed.settings
            tabs = [t for t in FEED_TABS if settings[t]]
            if not tabs:
                return
            timelines = [t for t in TIMELINES if any(FEED_TABS[tab][1] == t for tab in tabs)]   # Politics reads For you too
            if not (CFG["browser_enabled"] and self.browser_ready):
                return self.feed.set_status("error", "Milo's browser is off.")
            # never wait behind a chat or the user: try again later (no await between the check and the lock)
            if self.browser.controller == "user" or self.browser.lock_owner:
                return self.feed.set_status("waiting", "Milo's browser is busy. Milo will try again soon.")
            await self.browser.acquire("feed")
            try:
                got = await collect(self.browser, timelines)
            except SignedOut:
                return self.feed.set_status("signed_out", "Log in to X in Milo's browser.")
            finally:
                await self.browser.release_lock("feed")
            memory, goals = self.memory.read(), self.goals.context()

            async def brief(tab: str) -> None:
                read = got[FEED_TABS[tab][1]]
                posts = candidates(read, settings)
                if posts:
                    reply = await run_claude(brief_prompt(tab, posts, settings, memory, goals), CFG.get("model"), CLAUDE_DIR)
                    result = parse_brief(reply, posts, settings["top"], FEED_MOST.get(tab, 6))
                    shown = used_ids(result)
                    await add_linked([p for p in posts if p["id"] in shown])   # linked X posts show in place
                    self.feed.save_tab(tab, len(read), result, posts)
                elif tab not in self.feed.view()["tabs"]:   # an empty brief, so a new tab is not due again at once
                    self.feed.save_tab(tab, len(read), {"brief": [], "top": []}, [])

            await asyncio.gather(*(brief(t) for t in tabs))
            self.feed.set_status("ok")
            self.activity.record("feed", "Read your X feed", status="done",
                                 detail=", ".join(f"{TIMELINES[t][0]}: {len(got[t])} posts" for t in timelines))
        except Exception as e:
            log.exception("feed failed")
            self.feed.set_status("error", str(e)[:200] or e.__class__.__name__)
        finally:
            await self.broadcast({"t": "feed", "busy": False})

    async def cancel(self, conv: Conversation, grace: bool = False) -> None:
        """Stop the chat's turn. With grace (the user's Stop), a Stop that would end helper agents waits STOP_GRACE
        seconds, and the app offers Undo. A second Stop, or deleting the chat, stops at once."""
        if conv.pending_stop:
            conv.pending_stop.cancel()
            conv.pending_stop = None
        elif grace and conv.running and (agents := self._running_agents(conv)):
            conv.pending_stop = asyncio.create_task(self._stop_later(conv))
            await self.broadcast({"t": "stopping", "id": conv.id, "agents": agents, "grace": STOP_GRACE})
            return
        conv.stopping = conv.running
        conv.queue.clear()
        for m in conv.messages:
            if m.get("queued") and m.get("run"):
                self.scheduler.update_run(m["run"], "stopped")
        await self.drop_approvals(conv.id)
        if conv.running:
            await self.goose.cancel(conv.sid)
            # goose ends the turn but leaves Claude Code running under it, with its tools and subagents
            if not conv.halting:
                conv.halting = asyncio.create_task(self._halt(conv.sid, self._running_agents(conv)))

    async def _stop_later(self, conv: Conversation) -> None:
        await asyncio.sleep(STOP_GRACE)
        conv.pending_stop = None   # from here on Undo is too late
        await self.cancel(conv)

    async def keep(self, conv: Conversation) -> None:
        """Undo a Stop that is still waiting: the turn and its agents go on."""
        if conv.pending_stop:
            conv.pending_stop.cancel()
            conv.pending_stop = None
            await self.broadcast({"t": "stop_undone", "id": conv.id})

    async def fire_schedule(self, item: dict) -> None:
        self.activity.record("schedule", item["title"], item.get("source_conv"), "fired", item["text"])
        # one time: a side chat of its own; recurring: the task's one chat, where every run goes
        conv = await self.schedule_conversation(item)
        run = self.scheduler.log_run(item["id"], "running", conv.id)
        await self.submit(conv, item["text"], voice=False, scheduled=True, run=run)
        await self.broadcast({"t": "schedules"})

    def schedule_title(self, conv: Conversation) -> str:
        """Name of a task chat's Library folder: the schedule's title, which a chat rename does not change."""
        item = next((i for i in self.scheduler.store.data if i["id"] == conv.schedule), None)
        return item["title"] if item else conv.title

    async def schedule_conversation(self, item: dict) -> Conversation:
        """The hidden chat of a scheduled task. Every run works there; each reply goes to the main chat."""
        conv = next((c for c in self.convs.values() if c.schedule == item["id"]), None)
        return conv or await self.new_conversation(source="scheduled", title=item["title"], schedule=item["id"])

    def siri_conversation(self) -> Conversation | None:
        window = CFG["siri_session_minutes"] * 60
        recent = [c for c in self.convs.values() if c.source == "siri" and time.time() - c.updated < window]
        return max(recent, key=lambda c: c.updated, default=None)

    async def set_mode(self, mode: str) -> None:
        if any(c.running for c in self.convs.values()):
            raise HTTPException(409, "Wait for running tasks to finish before you change permissions.")
        await self.drop_approvals()
        await self.goose.restart(mode)


def google_client() -> tuple[str, str] | None:
    client_id = CFG.get("google_client_id")
    secret = keyring.get_password(KEYCHAIN_SERVICE, "google:client_secret") if client_id else None
    return (client_id, secret) if client_id and secret else None


hub = Hub()


async def start_browser() -> None:
    try:
        await hub.browser.start()
        await hub.browser_tools.start_upstream()
        hub.browser_ready = True
        log.info("browser mode ready")
    except Exception as e:
        log.error("browser mode disabled: %s", e)


def web_version() -> str:
    """Fingerprint of the PWA files. It changes when any file in web/ is edited, added or removed."""
    h = hashlib.sha1()
    for f in sorted(WEB.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(WEB)}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()[:12]


async def watch_web() -> None:
    """Tell connected phones to reload when the PWA files change."""
    version = web_version()
    while True:
        await asyncio.sleep(1)
        try:
            now = web_version()
        except OSError:
            continue
        if now != version:
            version = now
            log.info("web app changed (%s): telling phones to update", now)
            await hub.broadcast({"t": "update", "version": now})


async def feed_loop() -> None:
    """Read the X feed again when it is old, in the daytime, so the brief is ready when the user opens it."""
    await asyncio.sleep(120)   # after the browser is up
    while True:
        if hub.feed.due() and 7 <= time.localtime().tm_hour < 23:
            hub.refresh_feed()
        await asyncio.sleep(600)


async def release_loop() -> None:
    """Each goose session keeps its own Claude Code process, and each tab its own Chrome renderer: close the idle ones
    (Hub.release_sessions, Hub.close_tabs)."""
    cleaned = 0.0
    while True:
        await asyncio.sleep(60)
        try:
            await hub.release_sessions()
            await hub.close_tabs()
        except Exception:
            log.exception("releasing idle sessions and tabs failed")
        if time.time() - cleaned > 3600:   # old plots in Temp
            cleaned = time.time()
            await asyncio.to_thread(clean_temp, hub.temp)


async def start_google() -> None:
    try:
        await hub.google.start()
    except Exception as e:
        log.error("google accounts unavailable: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.goose.start()
    try:
        await hub.whisper.start()
    except Exception as e:
        log.error("voice input disabled: %s", e)
    hub.scheduler.start()
    browser_task = asyncio.create_task(start_browser()) if CFG["browser_enabled"] else None
    google_task = asyncio.create_task(start_google())
    web_task = asyncio.create_task(watch_web())
    feed_task = asyncio.create_task(feed_loop()) if CFG["browser_enabled"] else None
    release_task = asyncio.create_task(release_loop())
    voice_task = asyncio.create_task(asyncio.to_thread(hub.neural.voices))   # load the voice model now, not on the first reply
    async with hub.browser_tools.manager.run(), hub.google.manager.run(), hub.weather.manager.run(), \
            hub.planner.manager.run():
        log.info("Milo ready on http://127.0.0.1:%s (permissions: %s)", CFG["port"], CFG["permission_mode"])
        yield
    if browser_task:
        browser_task.cancel()
    google_task.cancel()
    web_task.cancel()
    if feed_task:
        feed_task.cancel()
    release_task.cancel()
    voice_task.cancel()
    await hub.google.up.stop()
    await hub.browser_tools.stop_upstream()
    await hub.browser.stop()
    await hub.goose.stop()
    await hub.whisper.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# Auth: every /api and /ws call needs the token (Authorization header, ?token= or X-Milo-Token).


def token_ok(token: str | None) -> bool:
    return bool(token) and secrets.compare_digest(token, CFG["token"])


def extract_token(headers, query) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return query.get("token") or headers.get("x-milo-token")


@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.url.path.startswith("/api/") and not token_ok(extract_token(request.headers, request.query_params)):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


def get_conv(cid: str) -> Conversation:
    conv = hub.convs.get(cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


# State and conversations


@app.get("/api/state")
async def state():
    convs = sorted(hub.convs.values(), key=lambda c: c.updated, reverse=True)
    return {
        "conversations": [c.summary() for c in convs],
        "mainId": hub.main_id(),
        "approvals": list(hub.approvals.values()),
        "settings": {k: CFG[k] for k in EDITABLE},
        "modes": MODES,
        "vapidKey": hub.push.public_key,
        "voiceInput": hub.whisper.proc is not None and hub.whisper.proc.returncode is None,
        "browser": {**hub.browser.state(), "enabled": CFG["browser_enabled"], "ready": hub.browser_ready},
    }


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    return get_conv(cid).full()


@app.post("/api/conversations/{cid}/read")
async def read_conversation(cid: str, request: Request):
    """The user saw the chat (up to `at`, its `updated` as the app had it). Read state lives here, not on the device,
    so every device drops the chat's dot (BEHAVIOR #92)."""
    conv = get_conv(cid)
    try:
        at = min(float((await request.json())["at"]), conv.updated)
    except Exception:   # no body: read up to now
        at = conv.updated
    if at > conv.read:
        conv.read = at
        hub.save()
        await hub.broadcast({"t": "read", "id": cid, "read": at})
    return conv.summary()


@app.patch("/api/conversations/{cid}")
async def rename_conversation(cid: str, request: Request):
    conv = get_conv(cid)
    title = " ".join(str((await request.json()).get("title", "")).split())[:80]
    if not title:
        raise HTTPException(400, "Give the chat a name")
    conv.title, conv.fixed_title = title, True   # goose no longer renames it
    hub.save()
    await hub.broadcast({"t": "title", "id": cid, "title": title})
    return conv.summary()


@app.post("/api/conversations/{cid}/compact")
async def compact_conversation(cid: str):
    """Compact now. The app has no control for it: Milo compacts by itself, silently, after a turn that leaves the chat
    over compact_at. The live suite uses this to test a compacted chat."""
    conv = get_conv(cid)
    if conv.running:
        raise HTTPException(409, "Wait for Milo to finish first.")
    if not conv.compacting:
        conv.compacting = asyncio.create_task(hub.compact(conv))
    if not await asyncio.shield(conv.compacting):
        raise HTTPException(502, "Couldn't compact this chat.")
    return conv.summary()


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    conv = get_conv(cid)
    if conv.main:
        raise HTTPException(400, "The main chat can't be deleted")
    await hub.cancel(conv)
    hub.convs.pop(cid, None)
    hub.save()
    await hub.broadcast({"t": "deleted", "id": cid})
    return {"ok": True}


@app.post("/api/approvals/{aid}")
async def answer_approval(aid: str, request: Request):
    await hub.resolve_approval(aid, (await request.json()).get("option"))
    return {"ok": True}


# Voice


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    return {"text": await hub.whisper.transcribe(audio, file.filename or "speech.m4a")}


async def say_audio(text: str) -> bytes:
    if hub.neural.is_voice(CFG["voice"]):
        return await hub.neural.synthesize(text, CFG["voice"], CFG["voice_rate"])
    voice = CFG["voice"] if not re.fullmatch(r"[ab][fm]_[a-z]+", CFG["voice"]) else "Samantha"
    return await synthesize(text, voice, CFG["voice_rate"])


@app.post("/api/tts")
async def tts(request: Request):
    """Speech for a reply. With "parts": true, returns the speakable text cut into parts (fetch each with "raw")."""
    body = await request.json()
    text = str(body.get("text", ""))
    if not body.get("raw"):
        text = speakable(text)
    if body.get("parts"):
        return {"parts": split_speech(text)}
    if not text.strip():
        raise HTTPException(400, "nothing to say")
    return Response(await say_audio(text), media_type="audio/mp4")


@app.get("/api/voices")
async def voices():
    natural = await asyncio.to_thread(hub.neural.voices)
    proc = await asyncio.create_subprocess_exec("say", "-v", "?", stdout=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    novelty = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Fred", "Good News", "Jester",
               "Junior", "Kathy", "Organ", "Ralph", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"}
    names = []
    for line in out.decode().splitlines():
        m = re.match(r"^(.+?)\s{2,}(en_\w+)", line)
        if m and m.group(1).strip() not in novelty:
            names.append({"name": m.group(1).strip(), "label": f"{m.group(1).strip()} (Mac)", "lang": m.group(2)})
    return natural + names


@app.post("/api/ask")
async def ask(request: Request):
    """Siri Shortcut endpoint: text (JSON or plain) or audio (multipart 'file'). Returns plain text to speak."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            text = await hub.whisper.transcribe(await upload.read(), upload.filename or "siri.m4a")
        else:
            text = str(form.get("text") or "").strip()
    elif ctype.startswith("application/json"):
        text = str((await request.json()).get("text") or "").strip()
    else:
        text = (await request.body()).decode().strip()
    if not text:
        return PlainTextResponse("I didn't catch that.")

    fresh = text.lower().startswith(("new conversation", "start over", "new chat"))
    conv = await hub.new_conversation(source="siri") if fresh else await hub.main_conv()
    busy = conv.running
    if busy:   # queued behind a running turn: the answer comes to the app, with a push
        await hub.submit(conv, text, voice=True)
        return PlainTextResponse("Added to your main chat. I'll get to it next.")
    waiter = asyncio.get_running_loop().create_future()
    hub.siri_wait[conv.id] = waiter
    await hub.submit(conv, text, voice=True)
    try:   # the Shortcut reads the answer out loud, and no push goes out
        return PlainTextResponse(await asyncio.wait_for(asyncio.shield(waiter), CFG["siri_wait_seconds"]))
    except asyncio.TimeoutError:
        hub.siri_wait.pop(conv.id, None)   # too slow: the answer arrives in the app, with a push
        return PlainTextResponse("Still working on that. I'll send it to your phone.")


# Muse features


@app.get("/api/activity")
async def activity():
    titles = {c.id: c.title for c in hub.convs.values()}
    return [{**e, "convTitle": titles.get(e.get("conv"))} for e in hub.activity.recent()]


@app.get("/api/library")
async def library():
    return hub.library.list()


@app.get("/api/library/today")
async def library_today(since: float | None = None):   # since: the phone's midnight, as the Mac and phone can differ
    return hub.library.today(since if since is not None else
                             time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))


@app.get("/api/library/favorites")
async def library_favorites():
    return hub.favorites.list()


@app.put("/api/library/favorites")
async def star_library_item(request: Request):   # {path, kind: file | folder, on}
    body = await request.json()
    try:
        hub.favorites.set(str(body.get("path", "")), str(body.get("kind", "")), bool(body.get("on", True)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "not in the Library")
    return hub.favorites.list()


@app.get("/api/library/file")
async def library_file(path: str, download: bool = False):
    try:
        p = hub.library.resolve(path)
    except FileNotFoundError:
        raise HTTPException(404, "file not found")
    # pages and SVGs from the Library never run scripts with the app's origin (and its token)
    scriptable = mimetypes.guess_type(p.name)[0] in SCRIPTABLE_TYPES
    if download:   # a type no browser shows inline: iOS would preview a PDF or a photo in place of the app
        return FileResponse(p, media_type="application/octet-stream",
                            headers={"Content-Disposition": attachment(p.name), "X-Content-Type-Options": "nosniff"})
    return FileResponse(p, content_disposition_type="inline", headers={"Content-Security-Policy": "sandbox"} if scriptable else None)


@app.get("/api/picture")
async def picture(path: str):
    """A picture in a reply: a Library path, or a full path in the Library, Temp or the browser's old output folder
    (screenshots sent before #85). Pictures only, no other files."""
    try:
        p = find_picture(path, [hub.library.root, hub.temp, OLD_OUTPUT])
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "picture not found")
    scriptable = mimetypes.guess_type(p.name)[0] in SCRIPTABLE_TYPES   # an SVG never runs with the app's origin
    return FileResponse(p, content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff", **({"Content-Security-Policy": "sandbox"} if scriptable else {})})


ZIP_MAX_FILES = 10_000
ZIP_MAX_BYTES = 4 * 1024 ** 3   # before compression: a folder bigger than this is better copied on the Mac


def attachment(name: str) -> str:
    """Content-Disposition for a download: a plain ASCII name for old browsers, the real one (RFC 5987) for the rest."""
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", name) or "download"
    return f"attachment; filename=\"{plain}\"; filename*=utf-8''{quote(name, safe='')}"


@app.get("/api/library/zip")
async def library_zip(path: str, check: bool = False):
    """A Library folder as <folder>.zip, made while it downloads. Hidden files and links out of the Library stay out.
    check only answers whether it can be made: the app asks first, as a failed link download says nothing."""
    try:
        folder = hub.library.resolve_dir(path)
    except FileNotFoundError:
        raise HTTPException(404, "folder not found")
    entries = await asyncio.to_thread(hub.library.zip_entries, folder)
    if not entries:
        raise HTTPException(404, "folder is empty")
    size = sum(p.stat().st_size for p, _ in entries)
    if len(entries) > ZIP_MAX_FILES or size > ZIP_MAX_BYTES:
        raise HTTPException(413, "folder is too large to download")
    if check:
        return {"files": len(entries), "size": size}
    return StreamingResponse(zip_stream(entries), media_type="application/zip",
                             headers={"Content-Disposition": attachment(f"{folder.name}.zip"), "Cache-Control": "no-store",
                                      "X-Content-Type-Options": "nosniff"})


SCRIPTABLE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}
PREVIEWS = DATA / "previews"
PREVIEW_DAYS = 7
preview_locks: dict[str, asyncio.Lock] = {}
# Added to Quick Look's pages. They are laid out for the width in their viewport tag, which a frame ignores: fit that
# width to the screen, as the iPhone's Quick Look does. A pinch zooms the page itself; page zoom of the whole app
# stays off (the keyboard check reads the visual viewport).
PREVIEW_JS = """<script>(() => {
const w = /width=(\\d+)/.exec(document.querySelector('meta[name=viewport]')?.content || '');
const fit = w ? Math.min(1, innerWidth / +w[1]) : 1;
let z = fit, s = 1;
const zoom = (v) => { z = Math.min(4, Math.max(fit, v)); document.documentElement.style.zoom = z; };
zoom(fit);
for (const t of ['gesturestart', 'gesturechange', 'gestureend']) addEventListener(t, (e) => { e.preventDefault();
  if (t === 'gesturestart') s = z; else if (t === 'gesturechange') zoom(s * e.scale); }, { passive: false });
})();</script>"""
PREVIEW_HEADERS = {"Cache-Control": f"private, max-age={PREVIEW_DAYS * 86400}", "X-Content-Type-Options": "nosniff"}


def preview_key(rel: str, p: Path) -> str:
    """Unguessable without the token, and new when the file changes: the preview URL itself is the access check."""
    st = p.stat()
    return hmac.new(CFG["token"].encode(), f"{rel}\0{st.st_mtime_ns}\0{st.st_size}".encode(), hashlib.sha256).hexdigest()[:32]


async def make_preview(src: Path, out: Path) -> None:
    """Quick Look on the Mac (the previews Finder shows) writes <name>.qlpreview/Preview.html and its parts."""
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    proc = await asyncio.create_subprocess_exec("qlmanage", "-p", "-o", str(tmp), str(src),
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), 60)
    except asyncio.TimeoutError:
        proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    tmp.rename(out)
    for old in PREVIEWS.iterdir():   # forget previews of old versions
        if time.time() - old.stat().st_mtime > PREVIEW_DAYS * 86400:
            shutil.rmtree(old, ignore_errors=True)


def preview_main(key: str) -> Path | None:
    d = next((PREVIEWS / key).glob("*.qlpreview"), None)
    return next((f for f in d.iterdir() if f.stem == "Preview"), None) if d else None


@app.get("/api/library/preview")
async def library_preview(path: str):
    """A preview of a Word, Excel, PowerPoint, Pages, Numbers ... file, made once per version. url is null without one."""
    try:
        p = hub.library.resolve(path)
    except FileNotFoundError:
        raise HTTPException(404, "file not found")
    key = preview_key(str(p.relative_to(hub.library.root.resolve())), p)
    async with preview_locks.setdefault(key, asyncio.Lock()):
        if not (PREVIEWS / key).exists():
            PREVIEWS.mkdir(exist_ok=True)
            try:
                await make_preview(p, PREVIEWS / key)
            except (OSError, asyncio.TimeoutError):
                log.exception("no preview for %s", path)
                return {"url": None, "type": None}
    preview_locks.pop(key, None)
    main = preview_main(key)
    return {"url": f"/preview/{key}/{main.name}" if main else None, "type": main and mimetypes.guess_type(main.name)[0]}


@app.get("/preview/{key}/{name}")
async def preview_file(key: str, name: str):
    """A part of a preview (page, sheet, style, script, image). Its pages run sandboxed, away from the app and its token."""
    d = next((PREVIEWS / key).glob("*.qlpreview"), None) if re.fullmatch(r"[0-9a-f]{32}", key) else None
    f = (d / name).resolve() if d and not name.startswith(".") else None
    if not f or f.parent != d.resolve() or not f.is_file():
        raise HTTPException(404, "not found")
    if f.suffix != ".html":
        return FileResponse(f, headers=PREVIEW_HEADERS)
    html = f.read_text(errors="replace")
    html = html.replace("</head>", PREVIEW_JS + "</head>", 1) if "</head>" in html else PREVIEW_JS + html
    return HTMLResponse(html, headers={**PREVIEW_HEADERS, "Content-Security-Policy": "sandbox allow-scripts; connect-src 'none'; form-action 'none'"})


MAX_UPLOAD = 50 * 1024 * 1024


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """A file attached with + in the app. Milo gets its path with the message."""
    data = await file.read(MAX_UPLOAD + 1)
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file is larger than 50 MB")
    p = hub.library.save_upload(file.filename or "file", data)
    return {"path": str(p.relative_to(hub.library.root)), "abs": str(p), "name": p.name, "size": len(data)}


@app.delete("/api/library/file")
async def library_delete(path: str):
    try:
        hub.library.resolve(path).unlink()
    except FileNotFoundError:
        raise HTTPException(404, "file not found")
    hub.favorites.forget(path)
    return {"ok": True}


# Goals and Ideas


@app.get("/api/goals")
async def goals():
    return hub.goals.list()


@app.post("/api/goals")
async def add_goal(request: Request):
    body = await request.json()
    try:
        g = hub.goals.add(str(body.get("title", "")), str(body.get("note", "")), str(body.get("section", "goal")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await hub.broadcast({"t": "goals"})
    return g


@app.patch("/api/goals/{gid}")
async def update_goal(gid: str, request: Request):
    body = await request.json()
    try:
        g = hub.goals.update(gid, **{k: body.get(k) for k in ("title", "note", "section", "done")})
    except KeyError:
        raise HTTPException(404, "goal not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    await hub.broadcast({"t": "goals"})
    return g


@app.delete("/api/goals/{gid}")
async def delete_goal(gid: str):
    hub.goals.delete(gid)
    await hub.broadcast({"t": "goals"})
    return {"ok": True}


IDEAS_MAX_AGE = 6 * 3600


@app.get("/api/ideas")
async def ideas():
    """The ideas. Older than 6 hours (or none yet): Milo makes new ones in the background."""
    if time.time() - hub.ideas.generated > IDEAS_MAX_AGE:
        hub.refresh_ideas()
    return {"items": hub.ideas.list(), "generated": hub.ideas.generated, "busy": hub.ideas_busy}


@app.post("/api/ideas/refresh")
async def refresh_ideas():
    hub.refresh_ideas()
    return {"busy": True}


@app.post("/api/ideas/{iid}/dismiss")
async def dismiss_idea(iid: str):
    hub.ideas.dismiss(iid)
    return {"ok": True}


# Feed (AI and political news from the user's X timelines)


@app.get("/api/feed")
async def feed():
    """The feed. When it is old (or there is none yet), Milo reads X again in the background."""
    if hub.feed.due():
        hub.refresh_feed()
    return {**hub.feed.view(), "busy": hub.feed_busy}


@app.post("/api/feed/refresh")
async def refresh_feed():
    hub.refresh_feed()
    return {"busy": True}


@app.put("/api/feed/settings")
async def feed_settings(request: Request):
    try:
        return hub.feed.update_settings(await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/feed/feedback")
async def feed_feedback(request: Request):
    """"Less like this" or "Mute" on a post."""
    body = await request.json()
    try:
        hub.feed.feedback(str(body.get("post", "")), str(body.get("kind", "")), str(body.get("tab", "")))
    except KeyError:
        raise HTTPException(404, "post not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/feed/vote")
async def feed_vote(request: Request):
    """Like or dislike a post ("" takes it back). Kept for later: briefs don't use votes yet."""
    body = await request.json()
    try:
        hub.feed.vote(str(body.get("post", "")), str(body.get("vote", "")), str(body.get("tab", "")))
    except KeyError:
        raise HTTPException(404, "post not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


FEED_MEDIA = DATA / "feed-media"
FEED_MEDIA_DAYS = 7
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


@app.get("/api/feed/media")
async def feed_media(u: str):
    """A feed image from X's image server, kept on the Mac for a week, so the phone loads it fast and only once."""
    if urlparse(u).scheme != "https" or urlparse(u).hostname != "pbs.twimg.com":
        raise HTTPException(400, "not an X image")
    FEED_MEDIA.mkdir(exist_ok=True)
    key = hashlib.sha1(u.encode()).hexdigest()
    f = next(FEED_MEDIA.glob(f"{key}.*"), None)
    if not f:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(u)
        except httpx.HTTPError:
            raise HTTPException(502, "could not load the image")
        ext = IMAGE_TYPES.get(r.headers.get("content-type", "").split(";")[0])
        if r.status_code != 200 or not ext:
            raise HTTPException(502, "could not load the image")
        f = FEED_MEDIA / f"{key}{ext}"
        f.write_bytes(r.content)
        for old in FEED_MEDIA.iterdir():   # forget images of old feeds
            if time.time() - old.stat().st_mtime > FEED_MEDIA_DAYS * 86400:
                old.unlink(missing_ok=True)
    return FileResponse(f, headers={"Cache-Control": f"private, max-age={FEED_MEDIA_DAYS * 86400}"})


@app.get("/api/schedules")
async def schedules():
    return hub.scheduler.store.data   # the order they were made in, so pausing or running one does not move it


@app.post("/api/schedules")
async def add_schedule(request: Request):
    body = await request.json()
    try:
        item = hub.scheduler.add(title=body.get("title") or body.get("text", "")[:60], text=body.get("text", ""),
                                 when=body.get("when"), cron=body.get("cron"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await hub.broadcast({"t": "schedules"})
    return item


@app.get("/api/schedules/{sid}/history")
async def schedule_history(sid: str):
    if not any(i["id"] == sid for i in hub.scheduler.store.data):
        raise HTTPException(404, "schedule not found")
    return hub.scheduler.history_of(sid)


@app.patch("/api/schedules/{sid}")
async def toggle_schedule(sid: str, request: Request):
    body = await request.json()
    item = hub.scheduler.set_auto_approve(sid, bool(body["auto_approve"])) if "auto_approve" in body else None
    if edit := {k: body[k] for k in ("when", "cron", "title", "text") if body.get(k)}:
        try:   # a new time, title or instruction in place: the task keeps its id, chat and runs
            item = hub.scheduler.edit(sid, **edit)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if "enabled" in body or not (edit or "auto_approve" in body):
        item = hub.scheduler.toggle(sid, bool(body.get("enabled")))
    if not item:
        raise HTTPException(404, "schedule not found")
    await hub.broadcast({"t": "schedules"})
    return item


@app.delete("/api/schedules/{sid}")
async def delete_schedule(sid: str):
    if not hub.scheduler.remove(sid):
        raise HTTPException(404, "schedule not found")
    await hub.broadcast({"t": "schedules"})
    return {"ok": True}


@app.post("/api/schedules/{sid}/run")
async def run_schedule(sid: str):
    item = next((i for i in hub.scheduler.store.data if i["id"] == sid), None)
    if not item:
        raise HTTPException(404, "schedule not found")
    await hub.fire_schedule(item)
    return {"ok": True}


@app.get("/api/memory")
async def get_memory():
    return {"text": hub.memory.read()}


@app.put("/api/memory")
async def put_memory(request: Request):
    hub.memory.write((await request.json()).get("text", ""))
    hub.activity.record("memory", "Memory edited", status="saved")
    return {"ok": True}


@app.get("/api/settings")
async def get_settings():
    return {k: CFG[k] for k in EDITABLE}


@app.put("/api/settings")
async def put_settings(request: Request):
    body = {k: v for k, v in (await request.json()).items() if k in EDITABLE}
    if "permission_mode" in body and body["permission_mode"] not in MODES:
        raise HTTPException(400, "unknown permission mode")
    if "voice_rate" in body:
        try:
            body["voice_rate"] = max(120, min(300, int(body["voice_rate"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "voice_rate is a number")
    # persona text: a blank name would leave the header empty; a very long one runs under the buttons
    for k, most in (("assistant_name", 40), ("tone", 300), ("length", 300)):
        if k in body:
            body[k] = " ".join(str(body[k]).split())[:most] or DEFAULTS[k]
    if body.get("permission_mode", CFG["permission_mode"]) != CFG["permission_mode"]:
        await hub.set_mode(body["permission_mode"])
    CFG.update(body)
    config.data = CFG
    config.save()
    if body.keys() & {"assistant_name", "tone", "length"}:
        for conv in hub.convs.values():
            conv.ctx = None  # re-send persona on the next turn
    return {k: CFG[k] for k in EDITABLE}


@app.get("/api/connectors")
async def connectors():
    path = Path.home() / ".config" / "goose" / "config.yaml"
    exts = (yaml.safe_load(path.read_text()) or {}).get("extensions", {}) if path.exists() else {}
    return sorted(({"name": v.get("display_name") or k, "id": k, "enabled": bool(v.get("enabled")),
                    "description": v.get("description", ""), "type": v.get("type", "")}
                   for k, v in exts.items()), key=lambda e: (not e["enabled"], e["name"].lower()))


USAGE = {"at": 0.0}   # the last reading, so opening Settings again soon doesn't run Claude Code again
USAGE_TTL = 30
CLI_CWD = Path(tempfile.gettempdir()) / "milo-cli"   # an empty folder, so Claude Code loads no project settings


async def claude_cli(*args: str, timeout: float = 30) -> str:
    """Claude Code's CLI on Milo's profile. For its local commands, which cost no tokens."""
    exe = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    CLI_CWD.mkdir(exist_ok=True)
    proc = await asyncio.create_subprocess_exec(exe, *args, cwd=CLI_CWD, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE,
                                                env={**os.environ, "CLAUDE_CONFIG_DIR": str(CLAUDE_DIR)})
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Claude Code took too long to answer")
    if proc.returncode != 0:
        raise RuntimeError((err or out).decode(errors="replace").strip()[-200:] or f"Claude Code stopped ({proc.returncode})")
    return out.decode()


@app.get("/api/usage")
async def usage():
    """The Claude plan's limits, from Claude Code's /usage. The limits count the whole account, not only Milo."""
    if time.time() - USAGE["at"] > USAGE_TTL:
        report, status = await asyncio.gather(
            claude_cli("-p", "/usage", "--output-format", "json", "--no-session-persistence", "--tools", "",
                       "--strict-mcp-config", "--setting-sources", ""),
            claude_cli("auth", "status", "--json"), return_exceptions=True)
        try:
            if isinstance(report, Exception):
                raise report
            result = json.loads(report)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(502, f"Claude Code: {e}")
        account = {} if isinstance(status, Exception) else json.loads(status)
        try:
            oauth = json.loads((CLAUDE_DIR / ".claude.json").read_text()).get("oauthAccount") or {}
        except (OSError, ValueError):
            oauth = {}
        USAGE.update(parse_usage(result.get("result") or ""), at=time.time(), email=account.get("email", ""),
                     plan=plan_name(oauth, account))
    return {k: v for k, v in USAGE.items() if k != "at"}


# Browser mode


@app.get("/api/browser/state")
async def browser_state():
    return {**hub.browser.state(), "enabled": CFG["browser_enabled"], "ready": hub.browser_ready}


@app.post("/api/browser/control")
async def browser_control(request: Request):
    action = (await request.json()).get("action")
    if action == "take":
        await hub.browser.take()
    elif action == "release":
        await hub.browser.release()
    else:
        raise HTTPException(400, "action must be 'take' or 'release'")
    hub.activity.record("browser", "You took over the browser" if action == "take" else "You gave the browser back",
                        hub.browser.lock_owner, "done", hub.browser.state()["url"])
    return hub.browser.state()


@app.post("/api/browser/navigate")
async def browser_navigate(request: Request):
    if hub.browser.controller != "user":
        raise HTTPException(409, "Take control of the browser first.")
    try:
        await hub.browser.navigate(str((await request.json()).get("url", "")).strip())
    except Exception as e:
        raise HTTPException(400, f"could not open the page: {e}")
    return hub.browser.state()


@app.post("/api/browser/tab")
async def browser_tab(request: Request):
    try:
        await hub.browser.select_tab(str((await request.json()).get("id", "")))
    except BrowserError as e:
        raise HTTPException(404, str(e))
    return hub.browser.state()


@app.post("/api/browser/restart")
async def browser_restart():
    await hub.browser.stop()
    await start_browser()
    return {**hub.browser.state(), "ready": hub.browser_ready}


@app.post("/api/browser/reset")
async def browser_reset():
    if hub.browser.lock_owner:
        raise HTTPException(409, "Milo is using the browser. Try again when the task ends.")
    await hub.browser.reset()
    await hub.browser_tools.restart_upstream()
    hub.activity.record("browser", "Browser data cleared", status="done")
    return hub.browser.state()


@app.get("/api/accounts")
async def accounts():
    return hub.vault.accounts()


@app.post("/api/accounts")
async def add_account(request: Request):
    body = await request.json()
    try:
        acct = hub.vault.add(domain=str(body.get("domain", "")), username=str(body.get("username", "")),
                             password=str(body.get("password", "")), label=str(body.get("label", "")),
                             totp=str(body.get("totp", "")), policy=str(body.get("policy", "ask")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.activity.record("browser", f"Account added: {acct['label']}", status="saved")
    return acct


@app.patch("/api/accounts/{aid}")
async def update_account(aid: str, request: Request):
    body = await request.json()
    try:
        return hub.vault.update(aid, **{k: body.get(k) for k in ("label", "domain", "username", "password", "totp", "policy")})
    except KeyError:
        raise HTTPException(404, "account not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/accounts/{aid}")
async def delete_account(aid: str):
    if not hub.vault.delete(aid):
        raise HTTPException(404, "account not found")
    hub.activity.record("browser", "Account deleted", status="done")
    return {"ok": True}


# Google accounts (several Gmail / Calendar / Drive accounts through milo-google)


@app.get("/api/google")
async def google_state():
    if hub.google.configured:
        try:   # a saved token may be dead: Settings then shows Sign in (cached, so this stays fast)
            await asyncio.wait_for(hub.google.check_tokens(), 6)
        except asyncio.TimeoutError:
            pass
    return {"configured": hub.google.configured, "client_id": CFG.get("google_client_id") or "",
            "accounts": hub.google.list_accounts(), "redirect": "http://localhost:8766/oauth2callback"}


@app.put("/api/google/client")
async def google_client_put(request: Request):
    body = await request.json()
    client_id, secret = str(body.get("client_id", "")).strip(), str(body.get("client_secret", "")).strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not secret:
        raise HTTPException(400, "Paste the Client ID (ends with .apps.googleusercontent.com) and the Client secret.")
    keyring.set_password(KEYCHAIN_SERVICE, "google:client_secret", secret)
    CFG["google_client_id"] = client_id
    config.data = CFG
    config.save()
    await hub.google.restart()
    for conv in hub.convs.values():
        conv.ctx = None
    hub.activity.record("google", "Google API client saved", status="saved")
    return await google_state()


async def google_sign_in(email: str, where: str) -> dict:
    before = hub.google.creds_mtime(email)   # a dead token's file is already there: wait for a new one
    try:
        url = await hub.google.sign_in_url(email)
    except Exception as e:
        raise HTTPException(409, str(e))
    if not url:
        return {"connected": True}
    reason = f"Sign in to Google as {email} and allow access. Then tap Give back."
    if where == "mac":
        await asyncio.create_subprocess_exec("open", url)
    else:
        await hub.browser.ensure_running()
        await hub.browser.take(reason)
        await hub.browser.navigate(url)
    asyncio.create_task(watch_google_sign_in(email, reason, before))
    hub.activity.record("google", f"Sign-in started for {email}", status="waiting")
    return {"connected": False, "where": where}


async def watch_google_sign_in(email: str, reason: str, before: float | None = None) -> None:
    for _ in range(900):
        if (mtime := hub.google.creds_mtime(email)) is not None and mtime != before:
            if hub.browser.controller == "user" and hub.browser.reason == reason:
                await hub.browser.release()
            for conv in hub.convs.values():
                conv.ctx = None   # tell the next turn about the new account
            hub.activity.record("google", f"Connected {email}", status="done")
            await hub.broadcast({"t": "toast", "text": f"Connected {email}"})
            await hub.broadcast({"t": "google"})
            return
        await asyncio.sleep(1)


@app.post("/api/google/accounts")
async def google_add(request: Request):
    if not hub.google.configured:
        raise HTTPException(409, "Set up the Google API client first.")
    body = await request.json()
    try:
        acct = hub.google.add(str(body.get("email", "")), str(body.get("label", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"account": acct, **await google_sign_in(acct["email"], str(body.get("where", "milo")))}


@app.post("/api/google/accounts/{email}/signin")
async def google_signin(email: str, request: Request):
    if not hub.google.find(email):
        raise HTTPException(404, "account not found")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await google_sign_in(email.lower(), str(body.get("where", "milo")))


@app.delete("/api/google/accounts/{email}")
async def google_remove(email: str):
    if not hub.google.remove(email):
        raise HTTPException(404, "account not found")
    for conv in hub.convs.values():
        conv.ctx = None
    hub.activity.record("google", f"Removed {email}", status="done")
    return {"ok": True}


# Permissions


@app.get("/api/permissions")
async def get_permissions():
    return {"mode": CFG["permission_mode"], "modes": MODES, "auto_read": hub.permissions.auto_read,
            "rules": hub.permissions.listing(), "browser_ready": hub.browser_ready,
            "accounts": hub.vault.accounts()}


@app.put("/api/permissions")
async def put_permissions(request: Request):
    body = await request.json()
    if "auto_read" in body:
        hub.permissions.set_auto_read(bool(body["auto_read"]))
    return await get_permissions()


@app.put("/api/permissions/rules")
async def put_rule(request: Request):
    body = await request.json()
    try:
        hub.permissions.set_rule(str(body.get("key", "")), str(body.get("rule", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return await get_permissions()


@app.delete("/api/permissions/rules")
async def reset_rules():
    hub.permissions.reset_rules()
    return await get_permissions()


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    hub.push.subscribe(await request.json())
    return {"ok": True}


@app.post("/api/push/test")
async def push_test():
    await hub.push.send("Notifications are on", "You will get alerts like this one.")   # not the name: iOS adds "from Milo"
    return {"ok": True, "devices": len(hub.push.subs.data)}


# Live updates


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not token_ok(extract_token(ws.headers, ws.query_params)):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.sockets[ws], hub.heard[ws] = True, time.time()
    await ws.send_json({"t": "hello", "version": web_version()})
    try:
        while True:
            msg = await ws.receive_json()
            hub.heard[ws] = time.time()
            kind = msg.get("type")
            try:
                if kind == "prompt":
                    # a second message sent before the app knew the new chat's id carries the first one's ref
                    cid = msg.get("id") or hub.refs.get(msg.get("ref") or "") or ""
                    conv = await hub.main_conv() if cid == "main" else hub.convs.get(cid) or await hub.new_conversation()
                    if msg.get("ref"):
                        hub.refs[msg["ref"]] = conv.id
                        while len(hub.refs) > 100:
                            hub.refs.pop(next(iter(hub.refs)))
                        await ws.send_json({"t": "bound", "ref": msg["ref"], "id": conv.id})
                    await hub.submit(conv, str(msg.get("text", "")).strip(), bool(msg.get("voice")))
                elif kind == "cancel" and (conv := hub.convs.get(msg.get("id", ""))):
                    await hub.cancel(conv, grace=not msg.get("now"))
                elif kind == "keep" and (conv := hub.convs.get(msg.get("id", ""))):
                    await hub.keep(conv)
                elif kind == "approve":
                    await hub.resolve_approval(msg.get("approval", ""), msg.get("option"))
                elif kind == "visible":
                    hub.sockets[ws] = bool(msg.get("value"))
                elif kind == "ping":
                    await ws.send_json({"t": "pong"})
            except HTTPException as e:
                await ws.send_json({"t": "error", "id": msg.get("id"), "message": e.detail})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.sockets.pop(ws, None)
        hub.heard.pop(ws, None)


@app.websocket("/ws/browser")
async def ws_browser(ws: WebSocket):
    """Live view: sends JPEG frames (binary) and state/meta (JSON); takes input while the user has control."""
    if not token_ok(extract_token(ws.headers, ws.query_params)):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        queue = await hub.browser.add_viewer()
    except Exception as e:
        await ws.send_json({"t": "error", "message": f"browser unavailable: {e}"})
        await ws.close()
        return

    async def pump():
        while True:
            item = await queue.get()
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_json(item)

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "ping":
                continue
            if hub.browser.controller != "user":
                await ws.send_json({"t": "error", "message": "Take control of the browser first."})
                continue
            try:
                if kind == "tap":
                    await hub.browser.tap(float(msg["x"]), float(msg["y"]))
                elif kind == "wheel":
                    await hub.browser.wheel(float(msg["x"]), float(msg["y"]), float(msg["dy"]))
                elif kind == "text":
                    await hub.browser.text(str(msg.get("text", ""))[:2000])
                elif kind == "key":
                    await hub.browser.key(str(msg.get("key", "")))
                elif kind == "nav":
                    await hub.browser.navigate(str(msg.get("url", "")))
                elif kind == "back":
                    await hub.browser.back()
                elif kind == "reload":
                    await hub.browser.reload()
            except Exception as e:
                await ws.send_json({"t": "error", "message": str(e)[:200]})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        await hub.browser.remove_viewer(queue)


# MCP endpoint for Claude Code (local only, bearer key); registered before the static mount below
app.router.routes.append(Route("/mcp/browser", endpoint=BrowserMCPApp(hub.browser_tools), methods=["GET", "POST", "DELETE"]))
app.router.routes.append(Route("/mcp/google", endpoint=GoogleMCPApp(hub.google), methods=["GET", "POST", "DELETE"]))
app.router.routes.append(Route("/mcp/weather", endpoint=WeatherMCPApp(hub.weather), methods=["GET", "POST", "DELETE"]))
app.router.routes.append(Route("/mcp/planner", endpoint=PlannerMCPApp(hub.planner), methods=["GET", "POST", "DELETE"]))


# PWA


@app.get("/")
async def index():
    html = (WEB / "index.html").read_text().replace(
        "<head>", f'<head>\n  <meta name="milo-version" content="{web_version()}">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse(WEB / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


class AppFiles(StaticFiles):
    """PWA files: the phone checks with the Mac before it uses a copy (a 304 if nothing changed)."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


app.mount("/", AppFiles(directory=WEB), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=CFG["port"], log_level="warning")
