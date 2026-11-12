"""A fake milo-google for the live behavior suite: the real tool list (google_tools.json, schemas only), answered from
fixed mail and calendar fixtures built around today. Nothing reaches Google. Writes (send, draft, events, labels,
Drive) are recorded and answered as if they worked, so the test can assert on what Milo tried."""

import copy
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from mcp import types

HERE = Path(__file__).parent
ACCOUNTS = [{"email": "alex@example.com", "label": "personal"},
            {"email": "alex.rivera@university.example.edu", "label": "school"},
            {"email": "alex.rivera@mail.university.example.edu", "label": "unimail"}]
PERSONAL, SCHOOL, UNIMAIL = (a["email"] for a in ACCOUNTS)
READ_WORDS = ("search", "get", "list", "query")


def load_tools() -> list[types.Tool]:
    return [types.Tool.model_validate(t) for t in json.loads((HERE / "google_tools.json").read_text())]


def text_result(text: str, error: bool = False) -> types.CallToolResult:
    # workspace-mcp's tools declare an output schema {"result": str}: a result without it is an error to the client
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error,
                                structured_content=None if error else {"result": text})


def fixtures(now: datetime | None = None) -> dict:
    """Mail and events around today, in local time."""
    now = (now or datetime.now()).astimezone()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(d: int, h: int, m: int = 0) -> datetime:
        return day + timedelta(days=d, hours=h, minutes=m)

    def ago(hours: float) -> str:
        return (now - timedelta(hours=hours)).strftime("%a, %d %b %Y %H:%M:%S %z")

    events = [
        {"id": "ev-physio", "account": PERSONAL, "title": "Physio", "start": at(0, 15), "end": at(0, 16), "details": ""},
        {"id": "ev-chen", "account": SCHOOL, "title": "Chen/Alex Meeting", "start": at(0, 17, 30), "end": at(0, 18),
         "details": "Weekly advisor meeting"},
        {"id": "ev-robotics", "account": SCHOOL, "title": "Robotics Class", "start": at(1, 12, 45), "end": at(1, 14),
         "details": "Introduction to Robotics, Room 1300"},
        {"id": "ev-busy", "account": UNIMAIL, "title": "Busy", "start": at(2, 10), "end": at(2, 10, 30), "details": ""},
        {"id": "ev-dentist", "account": PERSONAL, "title": "Dentist", "start": at(3, 9), "end": at(3, 10), "details": ""},
    ]
    mail = [
        {"id": "m-li", "thread": "t-li", "account": SCHOOL, "from": "Tobias Wren <twren@uni.example.edu>",
         "to": SCHOOL, "subject": "Meeting slots next week", "date": ago(1.2), "unread": True,
         "msgid": "<CAL1li-77@mail.gmail.com>", "labels": ["INBOX", "UNREAD"],
         "body": "Hi Alex,\n\nCould you send me two or three time slots for a meeting next week? Please reply by "
                 "Friday so I can set it up with Chen and Marco.\n\nBest,\nTobias"},
        {"id": "m-medium", "thread": "t-medium", "account": PERSONAL, "from": "Medium Daily Digest <noreply@medium.com>",
         "to": PERSONAL, "subject": "Top stories for you: 10 agent frameworks compared", "date": ago(1.5), "unread": True,
         "msgid": "<medium-digest-1@medium.com>", "labels": ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
         "body": "Today's highlights from writers you follow. Unsubscribe at any time."},
        {"id": "m-sam", "thread": "t-sam", "account": SCHOOL, "from": "Sam Porter <sporter@university.example.edu>",
         "to": "eng6100-students@university.example.edu", "cc": SCHOOL, "subject": "Hydra SSH keys for ENG 6100", "date": ago(20),
         "unread": False, "msgid": "<CAJ8sam-412@mail.gmail.com>", "labels": ["INBOX"],
         "body": "Hi all,\n\nTo get Hydra access for ENG 6100, each student needs to send me their public SSH key. "
                 "Please email it to me directly.\n\nThanks,\nSam Porter\nUniversity IT Services"},
        {"id": "m-dana", "thread": "t-dana", "account": PERSONAL, "from": "Dana Brooks <dana.brooks@recruitco.example.com>",
         "to": PERSONAL, "subject": "Following up: ML Engineer role", "date": ago(3), "unread": True,
         "msgid": "<db-9921@recruitco.example.com>", "labels": ["INBOX", "UNREAD"],
         "body": "Hi Alex,\n\nThanks for your interest in the ML Engineer role. Could you confirm whether you would need "
                 "a relocation package, and send your latest resume?\n\nBest,\nDana"},
        {"id": "m-github", "thread": "t-github", "account": PERSONAL, "from": "GitHub <notifications@github.com>",
         "to": PERSONAL, "subject": "[alex-rivera.github.io] Pages build succeeded", "date": ago(0.8), "unread": True,
         "msgid": "<gh-build-5@github.com>", "labels": ["INBOX", "UNREAD", "CATEGORY_UPDATES"],
         "body": "Your GitHub Pages site was built and deployed."},
    ]
    return {"events": events, "mail": mail}


class FakeGoogle:
    def __init__(self):
        self.tools = load_tools()
        self.reset()

    def reset(self) -> None:
        self.data = fixtures()
        self.calls: list[dict] = []    # every call, in order
        self.drafts: list[dict] = []
        self.fail: set[str] = set()    # tools that answer with an error, as Google did on 2026-10-27

    def add_events(self, events: list[dict]) -> None:
        """A case's own events: {"id", "account": "personal"|"school"|"unimail", "title", "day" (from today),
        "start" and "end" ("HH:MM"), "details"}."""
        accounts = dict(zip(("personal", "school", "unimail"), (PERSONAL, SCHOOL, UNIMAIL)))
        day = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        for e in events:
            (sh, sm), (eh, em) = (map(int, e[k].split(":")) for k in ("start", "end"))
            base = day + timedelta(days=e.get("day", 0))
            self.data["events"].append({"id": e["id"], "account": accounts[e.get("account", "personal")],
                                        "title": e["title"], "start": base.replace(hour=sh, minute=sm),
                                        "end": base.replace(hour=eh, minute=em), "details": e.get("details", "")})

    # helpers

    def _mail_for(self, email: str) -> list[dict]:
        return [m for m in self.data["mail"] + self.drafts if m["account"] == email]

    @staticmethod
    def _headers(m: dict) -> str:
        lines = [f"Subject: {m['subject']}", f"From: {m['from']}", f"To: {m['to']}"]
        if m.get("cc"):
            lines.append(f"Cc: {m['cc']}")
        lines += [f"Date: {m['date']}", f"Message-ID: {m['msgid']}"]
        if m.get("in_reply_to"):
            lines += [f"In-Reply-To: {m['in_reply_to']}", f"References: {m.get('references') or m['in_reply_to']}"]
        return "\n".join(lines)

    def _full(self, m: dict) -> str:
        return f"Message ID: {m['id']}\nThread ID: {m['thread']}\nLabels: {', '.join(m['labels'])}\n" \
               f"{self._headers(m)}\n\n--- BODY ---\n{m['body']}"

    def _search(self, email: str, query: str) -> str:
        q = (query or "").lower()
        items = self._mail_for(email)
        if "in:draft" in q or "is:draft" in q:
            items = [m for m in items if "DRAFT" in m["labels"]]
        else:
            items = [m for m in items if "DRAFT" not in m["labels"]]
            if "in:sent" in q or "is:sent" in q:
                items = [m for m in items if "SENT" in m["labels"]]
            if "is:unread" in q:
                items = [m for m in items if m.get("unread")]
            words = [w for w in re.findall(r"(?:from|subject|to):(\S+)|\"([^\"]+)\"", q)]
            terms = [a or b for a, b in words]
            bare = [w.strip("()\"") for w in re.sub(r"\"[^\"]+\"", " ", q).split()
                    if ":" not in w and w not in ("or", "and", "{", "}") and len(w.strip("()\"")) > 2]

            def text(m: dict) -> str:
                return (m["from"] + m["subject"] + m["to"] + m["body"]).lower()

            if terms:
                items = [m for m in items if all(t.strip("()") in text(m) for t in terms)]
            if bare:
                items = [m for m in items if any(w in text(m) for w in bare)]
        if not items:
            return f"No messages found for query: '{query}'"
        rows = [f"{i + 1}. Message ID: {m['id']}\n   Thread ID: {m['thread']}\n   From: {m['from']}\n"
                f"   Subject: {m['subject']}\n   Date: {m['date']}\n   Web Link: https://mail.google.com/mail/u/0/#all/{m['id']}"
                for i, m in enumerate(items)]
        return f"Found {len(items)} messages matching '{query}':\n\n" + "\n\n".join(rows)

    def _find(self, mid: str) -> dict | None:
        return next((m for m in self.data["mail"] + self.drafts if m["id"] == mid), None)

    @staticmethod
    def _parse_time(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return t if t.tzinfo else t.astimezone()
        except ValueError:
            try:
                return datetime.fromisoformat(s[:10]).astimezone()
            except ValueError:
                return None

    def _events(self, email: str, args: dict) -> str:
        lo, hi = self._parse_time(args.get("time_min")), self._parse_time(args.get("time_max"))
        cal = str(args.get("calendar_id") or "primary")
        rows = []
        for e in self.data["events"]:
            if e["account"] != email or (cal not in ("primary", email)):
                continue
            if lo and e["end"] <= lo or hi and e["start"] >= hi:
                continue
            if args.get("query") and args["query"].lower() not in e["title"].lower():
                continue
            rows.append(f'- "{e["title"]}" (Starts: {e["start"].isoformat()}, Ends: {e["end"].isoformat()}) '
                        f'ID: {e["id"]}' + (f' | Description: {e["details"]}' if e["details"] else ""))
        if not rows:
            return f"No events found in calendar '{cal}' for {email} for the specified time range."
        return f"Successfully retrieved {len(rows)} events from calendar '{cal}' for {email}:\n" + "\n".join(rows)

    # the MCP call

    async def call(self, name: str, args: dict) -> types.CallToolResult:
        args = dict(args or {})
        self.calls.append({"ts": time.time(), "tool": name, "args": copy.deepcopy(args)})
        if name in self.fail:
            return text_result(f"An unexpected error occurred in {name}: the Google API did not answer in time.", True)
        if name == "google_list_accounts":
            return text_result(json.dumps([{**a, "connected": True} for a in ACCOUNTS], indent=1))
        email = str(args.get("user_google_email") or "").lower().strip()
        if email not in (a["email"] for a in ACCOUNTS):
            return text_result(f"Pass user_google_email. Connected accounts: {', '.join(a['email'] for a in ACCOUNTS)}",
                               True)
        if name == "search_gmail_messages":
            return text_result(self._search(email, args.get("query", "")))
        if name in ("get_gmail_message_content", "get_gmail_messages_content_batch"):
            ids = args.get("message_ids") or [args.get("message_id")]
            found = [self._find(str(i)) for i in ids if i]
            return text_result("\n\n=====\n\n".join(self._full(m) if m else "Message not found." for m in found)
                               or "Message not found.")
        if name == "get_gmail_thread_content":
            msgs = [m for m in self.data["mail"] + self.drafts if m["thread"] == args.get("thread_id")]
            if not msgs:
                return text_result("Thread not found.", True)
            return text_result(f"Thread ID: {args.get('thread_id')}\nMessages: {len(msgs)}\n\n" +
                               "\n\n=====\n\n".join(self._full(m) for m in msgs))
        if name in ("draft_gmail_message", "send_gmail_message"):
            sent = name == "send_gmail_message"
            m = {"id": f"{'s' if sent else 'r'}-eval-{len(self.calls)}", "thread": args.get("thread_id") or f"t-new-{len(self.calls)}",
                 "account": email, "from": email, "to": args.get("to") or "", "cc": args.get("cc") or "",
                 "subject": args.get("subject") or "", "date": datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z"),
                 "msgid": f"<eval-{len(self.calls)}@mail.gmail.com>", "labels": ["SENT"] if sent else ["DRAFT"],
                 "body": args.get("body") or "", "in_reply_to": args.get("in_reply_to"), "references": args.get("references")}
            self.drafts.append(m)
            if sent:
                return text_result(f"Email sent! Message ID: {m['id']}")
            return text_result(f"Draft created! Draft ID: {m['id']}, Message ID: {m['id']}")
        if name == "list_calendars":
            return text_result(f"Calendars for {email}:\n- \"{email}\" (Primary) ID: {email}")
        if name == "get_events":
            return text_result(self._events(email, args))
        if name == "query_freebusy":
            lo, hi = self._parse_time(args.get("time_min")), self._parse_time(args.get("time_max"))
            busy = [f"{e['start'].isoformat()} - {e['end'].isoformat()}" for e in self.data["events"]
                    if e["account"] == email and not (lo and e["end"] <= lo or hi and e["start"] >= hi)]
            return text_result(f"Busy times for {email}:\n" + ("\n".join(busy) or "none"))
        if name == "list_gmail_labels":
            return text_result("Labels: INBOX, UNREAD, SENT, DRAFT, CATEGORY_PROMOTIONS, CATEGORY_UPDATES")
        if any(name.startswith(w) for w in READ_WORDS):
            return text_result("No results found.")
        return text_result(f"Done. ({name} completed)")   # any other write: recorded, answered as done
