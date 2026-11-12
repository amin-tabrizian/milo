"""The milo-planner MCP server: the user's days in one view, and a check of every plan, in code (BEHAVIOR #94).

Before this, each briefing, check-in and plan was built by the model from three calendar reads, a curl of busy.json
and Tasks.md, guided by prose rules. It often skipped a source, packed a day with no breaks, placed work inside
meetings or before 10 am, and wrote the calendar and Tasks.md differently. Here:
- day_view reads every source for a range of days (all Google calendars, the busy.json work feed, Tasks.md) and
  gives the events, the planned blocks, what is due, the free time left and the focus hours left. A source that
  fails is named, and no time is called free then.
- check_plan checks proposed blocks against the user's rules (Instructions/Planning rules.md) and the day view.
- workload compares the hours each task still needs with the free hours before its due date.
- plan_block adds, moves or removes a work block on the calendar and on the task's line in Tasks.md together.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from mcp import types
from mcp.server.lowlevel import Server

from mcp_proxy import BearerEndpoint, session_manager

log = logging.getLogger("planner-mcp")

BUSY_URL = ""   # a busy-times feed ({"days": {"YYYY-MM-DD": [[start min, end min]]}}): busy_url in data/config.json
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# the rules the checker uses when Planning rules.md does not set them
DEFAULT_RULES = {"day_start": "10:00", "day_end": "22:00", "break_minutes": 15, "max_focus_hours": 6,
                 "max_day_hours": 8, "max_block_hours": 3,
                 "rest_days": "Sat", "work_only_days": "Thu", "class_words": "class", "before_class_minutes": 60,
                 "class_prep_hours": 4, "default_calendar": "personal"}
RULE_LINE = re.compile(r"^\s*-\s*([a-z_]+)\s*:\s*([^(#\n]*)", re.M)
EVENT_LINE = re.compile(r'^- "(?P<title>.*?)" \(Starts: (?P<start>[0-9T:+\-.Z]+)[^,]*, Ends: (?P<end>[0-9T:+\-.Z]+)'
                        r'[^)]*\)(?: ID: (?P<id>\S+))?', re.M)
TASK_LINE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<body>.+)$")
DUE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")
PLAN_ITEM = re.compile(r"(?:(?P<wd>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(?P<m>\d{1,2})-(?P<d>\d{1,2})\s+"
                       r"(?P<s>\d{1,2}:\d{2})\s*-\s*(?P<e>\d{1,2}:\d{2})")
EST = re.compile(r"\best:\s*(\d+(?:\.\d+)?)\s*h", re.I)
NEEDS = re.compile(r"\b(?:needs|about|~)\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*h(?:ours?)?\b", re.I)

Fetch = Callable[[str], Awaitable[dict]]
Call = Callable[[str, dict], Awaitable[types.CallToolResult]]


async def fetch_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(url, params={"t": int(datetime.now().timestamp())})   # past the CDN's cache
        r.raise_for_status()
        return r.json()


def text_result(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def local(d: date, clock: str) -> datetime:
    h, m = map(int, clock.split(":"))
    return datetime.combine(d, dtime(h % 24, m)).astimezone()


def parse_time(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.astimezone()


def hours(blocks) -> float:
    return round(sum((e - s).total_seconds() for s, e in blocks) / 3600, 2)


def short(text: str, n: int = 80) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


# rules

def load_rules(path: Path | None) -> dict:
    rules = dict(DEFAULT_RULES)
    if path and path.exists():
        for key, value in RULE_LINE.findall(path.read_text()):
            if key in DEFAULT_RULES and value.strip():
                rules[key] = value.strip()
    out = dict(rules)
    for k in ("break_minutes", "before_class_minutes"):
        out[k] = int(float(rules[k]))
    for k in ("max_focus_hours", "max_day_hours", "max_block_hours", "class_prep_hours"):
        out[k] = float(rules[k])
    for k in ("rest_days", "work_only_days"):
        out[k] = [d[:3].title() for d in re.split(r"[,\s]+", str(rules[k])) if d[:3].title() in DAYS]
    out["class_words"] = [w.lower() for w in re.split(r"[,\s]+", str(rules["class_words"])) if w]
    return out


# Tasks.md

@dataclass
class Task:
    line: int
    done: bool
    title: str
    due: date | None
    plan: list[tuple[datetime, datetime]]
    est: float | None
    raw: str
    parts: list[str] = field(default_factory=list)

    @property
    def planned_hours(self) -> float:
        return hours(self.plan)


def plan_items(segment: str, year: int) -> list[tuple[datetime, datetime]]:
    out = []
    for m in PLAN_ITEM.finditer(segment):
        try:
            d = date(year, int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        s, e = local(d, m["s"]), local(d, m["e"])
        out.append((s, e if e > s else e + timedelta(days=1)))
    return out


def parse_tasks(text: str, today: date) -> list[Task]:
    tasks = []
    for i, line in enumerate(text.splitlines()):
        m = TASK_LINE.match(line)
        if not m:
            continue
        parts = [p.strip() for p in m["body"].split(" | ")]
        due = None
        if len(parts) > 1 and (dm := DUE.match(parts[1])):
            due = date.fromisoformat(dm[1])
        plan = []
        for p in parts[2:]:
            if p.lower().startswith("plan:"):
                year = due.year if due else today.year
                plan += plan_items(p[5:], year)
        est = None
        for p in parts:
            if em := EST.search(p):
                est = float(em[1])
        if est is None and (nm := NEEDS.search(m["body"])):
            est = float(nm[2] or nm[1])
        tasks.append(Task(i, m["mark"] != " ", parts[0], due, plan, est, line, parts))
    return tasks


def find_task(tasks: list[Task], query: str) -> tuple[Task | None, list[Task]]:
    """The open task a query names: the one whose title holds the query, or else shares the most words with it."""
    open_ = [t for t in tasks if not t.done]
    q = query.lower().strip()
    hits = [t for t in open_ if q and q in t.title.lower()]
    if len(hits) == 1:
        return hits[0], hits
    if not hits:
        qw = words(query) - {"the", "a", "an", "for", "to", "of", "and", "on", "my"}
        scored = sorted(((len(qw & words(t.title)), t) for t in open_), key=lambda x: -x[0])
        best = [t for n, t in scored if n and n == scored[0][0]] if scored else []
        if len(best) == 1 and scored[0][0] >= max(1, len(qw) // 2):
            return best[0], best
        hits = best
    return None, hits


def set_plan(line: str, plan: list[tuple[datetime, datetime]]) -> str:
    """The task line with its plan: segment written from plan (dropped when empty)."""
    parts = line.split(" | ")
    parts = [p for p in parts if not p.strip().lower().startswith("plan:")
             and p.strip().lower() not in ("not on calendar", "no block planned yet")]
    if plan:
        items = "; ".join(f"{DAYS[s.weekday()]} {s.month:02d}-{s.day:02d} {hm(s)}-{hm(e)}" for s, e in sorted(plan))
        parts.append(f"plan: {items}")
    return " | ".join(parts)


# the merged view

@dataclass
class Day:
    day: date
    events: list[dict] = field(default_factory=list)     # Google events: start, end, title, calendar
    allday: list[str] = field(default_factory=list)
    busy: list[tuple[datetime, datetime]] = field(default_factory=list)   # work feed, no titles
    planned: list[dict] = field(default_factory=list)    # task blocks: start, end, task
    due: list[Task] = field(default_factory=list)


class PlannerTools:
    def __init__(self, *, key: str, google_call: Call, accounts: Callable[[], list[dict]], tasks_path: Path,
                 rules_path: Path | None, busy_url: str = BUSY_URL, fetch: Fetch = fetch_json,
                 now: Callable[[], datetime] = lambda: datetime.now().astimezone()):
        self.key = key
        self.google_call = google_call
        self.accounts = accounts       # () -> [{"email", "label", "connected"}]
        self.tasks_path = tasks_path
        self.rules_path = rules_path
        self.busy_url = busy_url
        self.fetch = fetch
        self.now = now
        # (chat key, tool, args) -> why the call is refused, or None; the bridge sets it (calendar writes need an OK)
        self.guard: Callable[[str | None, str, dict], str | None] | None = None
        self.write_lock = asyncio.Lock()
        self.server = Server("milo-planner", version="1.0",
                             instructions="The user's days and plans: read a day with day_view, check a plan with "
                                          "check_plan before you propose it, change work blocks with plan_block.",
                             on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.manager = session_manager(self.server)

    # sources

    def rules(self) -> dict:
        return load_rules(self.rules_path)

    def tasks(self) -> list[Task]:
        return parse_tasks(self.tasks_path.read_text() if self.tasks_path.exists() else "", self.now().date())

    async def _events(self, start: date, end: date) -> tuple[list[dict], list[str]]:
        accts = [a for a in self.accounts() if a.get("connected", True)]
        lo, hi = local(start, "00:00"), local(end + timedelta(days=1), "00:00")

        async def one(a: dict) -> tuple[dict, types.CallToolResult | Exception]:
            try:
                return a, await self.google_call("get_events", {
                    "user_google_email": a["email"], "calendar_id": "primary", "time_min": lo.isoformat(),
                    "time_max": hi.isoformat(), "max_results": 250, "single_events": True})
            except Exception as e:   # one calendar failing must not hide the others
                return a, e
        events, failed, seen = [], [], set()
        for a, r in [await one(a) for a in accts]:   # milo-google takes one account at a time anyway
            text = "" if isinstance(r, Exception) else " ".join(c.text for c in r.content if isinstance(c, types.TextContent))
            if isinstance(r, Exception) or r.is_error:
                failed.append(f"{a.get('label') or a['email']} calendar")
                continue
            for m in EVENT_LINE.finditer(text):
                title = m["title"].replace('\\"', '"')
                if "T" not in m["start"]:
                    events.append({"allday": True, "day": date.fromisoformat(m["start"][:10]), "title": title})
                    continue
                s, e = parse_time(m["start"]), parse_time(m["end"])
                if (title.lower(), s, e) in seen:   # the same event on two calendars shows once
                    continue
                seen.add((title.lower(), s, e))
                events.append({"start": s, "end": e, "title": title, "calendar": a.get("label") or a["email"],
                               "id": m["id"], "email": a["email"]})
        if not accts:
            failed.append("no Google account connected")
        return events, failed

    async def _busy(self, start: date, end: date) -> tuple[list[tuple[datetime, datetime]], str | None]:
        if not self.busy_url:   # no feed set up: the Google calendars are all there is
            return [], None
        try:
            data = await self.fetch(self.busy_url)
        except Exception as e:
            log.warning("busy.json: %r", e)
            return [], "work calendar (busy.json)"
        out, d = [], start
        while d <= end:
            for s, e in (data.get("days") or {}).get(d.isoformat(), []):
                out.append((local(d, "00:00") + timedelta(minutes=s), local(d, "00:00") + timedelta(minutes=e)))
            d += timedelta(days=1)
        return out, None

    async def load(self, start: date, end: date) -> tuple[list[Day], list[str], list[Task]]:
        (events, failed), (busy, busy_failed) = await asyncio.gather(self._events(start, end), self._busy(start, end))
        if busy_failed:
            failed.append(busy_failed)
        tasks = self.tasks()
        days, d = {}, start
        while d <= end:
            days[d] = Day(d)
            d += timedelta(days=1)
        planned = [(s, e, t) for t in tasks if not t.done for s, e in t.plan]
        for ev in events:
            if ev.get("allday"):
                if ev["day"] in days:
                    days[ev["day"]].allday.append(ev["title"])
                continue
            if ev["start"].date() not in days:
                continue
            # Milo's own work block, on the calendar and on its task's line: it shows once, as planned work
            if any(abs((ev["start"] - s).total_seconds()) < 60 and abs((ev["end"] - e).total_seconds()) < 60
                   for s, e, _ in planned):
                continue
            days[ev["start"].date()].events.append(ev)
        for s, e in busy:
            if s.date() in days and not any(ev["start"] <= s and e <= ev["end"] for ev in days[s.date()].events):
                days[s.date()].busy.append((s, e))   # a feed block that is also a named event shows once, named
        for s, e, t in planned:
            if s.date() in days:
                days[s.date()].planned.append({"start": s, "end": e, "task": t})
        for t in tasks:
            if not t.done and t.due in days:
                days[t.due].due.append(t)
        for day in days.values():
            day.events.sort(key=lambda x: x["start"])
            day.busy.sort()
            day.planned.sort(key=lambda x: x["start"])
        return list(days.values()), failed, tasks

    # the rules applied to a day

    def is_class(self, title: str, rules: dict) -> bool:
        return any(w in title.lower() for w in rules["class_words"])

    def taken(self, day: Day, rules: dict, skip_task: Task | None = None) -> list[tuple[datetime, datetime, str]]:
        """Everything fixed on a day, as (start, end, what): events, work meetings and planned blocks."""
        out = [(e["start"], e["end"], e["title"]) for e in day.events]
        out += [(s, e, "a work meeting (busy)") for s, e in day.busy]
        out += [(p["start"], p["end"], f"the block for {short(p['task'].title, 50)}") for p in day.planned
                if p["task"] is not skip_task]
        return sorted(out)

    def free(self, day: Day, rules: dict) -> list[tuple[datetime, datetime]]:
        """Free time for work: inside the working hours, outside everything taken, with a break around it and no
        work in the time before a class."""
        if DAYS[day.day.weekday()] in rules["rest_days"]:
            return []
        lo, hi = local(day.day, rules["day_start"]), local(day.day, rules["day_end"])
        gap = timedelta(minutes=rules["break_minutes"])
        blocked = [(s - gap, e + gap) for s, e, _ in self.taken(day, rules)]
        blocked += [(e["start"] - timedelta(minutes=rules["before_class_minutes"]), e["start"])
                    for e in day.events if self.is_class(e["title"], rules)]
        if day.day == self.now().date():
            blocked.append((lo, max(lo, self.now())))
        out, cur = [], lo
        for s, e in sorted(blocked):
            if s > cur:
                out.append((cur, min(s, hi)))
            cur = max(cur, e)
            if cur >= hi:
                break
        if cur < hi:
            out.append((cur, hi))
        return [(s, e) for s, e in out if (e - s) >= timedelta(minutes=30)]

    def day_json(self, day: Day, rules: dict, failed: list[str]) -> dict:
        wd = DAYS[day.day.weekday()]
        focus = hours((p["start"], p["end"]) for p in day.planned)
        out = {"date": day.day.isoformat(), "day": wd}
        if wd in rules["rest_days"]:
            out["rule"] = "rest day: plan no work"
        elif wd in rules["work_only_days"]:
            out["rule"] = "work day: only work tasks"
        out["events"] = [f"{hm(e['start'])}-{hm(e['end'])} {e['title']} ({e['calendar']})" for e in day.events]
        if day.allday:
            out["all_day"] = day.allday
        if day.busy:
            out["work_meetings_busy"] = [f"{hm(s)}-{hm(e)}" for s, e in day.busy]
        out["planned_work"] = [f"{hm(p['start'])}-{hm(p['end'])} {short(p['task'].title, 60)}" for p in day.planned]
        out["due"] = [short(t.title) for t in day.due]
        if failed:
            out["free"] = "unknown: " + ", ".join(failed) + " could not be read"
        else:
            free = self.free(day, rules)
            out["free"] = [f"{hm(s)}-{hm(e)}" for s, e in free]
            fixed = hours([(e["start"], e["end"]) for e in day.events] + day.busy)
            left = min(rules["max_focus_hours"] - focus, rules["max_day_hours"] - fixed - focus, hours(free))
            out["focus_hours"] = {"planned": focus, "meetings_and_classes": fixed, "cap": rules["max_focus_hours"],
                                  "day_cap": rules["max_day_hours"], "left": max(0.0, round(left, 2))}
        return out

    # tools

    async def day_view(self, start: str | None = None, days: int = 1) -> dict:
        today = self.now().date()
        first = date.fromisoformat(start) if start else today
        days = max(1, min(int(days or 1), 14))
        loaded, failed, tasks = await self.load(first, first + timedelta(days=days - 1))
        rules = self.rules()
        out = {"days": [self.day_json(d, rules, failed) for d in loaded]}
        if first <= today:
            overdue = sorted((t for t in tasks if not t.done and t.due and t.due < today), key=lambda t: t.due)
            if overdue:
                out["overdue"] = {"count": len(overdue),
                                  "items": [f"{short(t.title, 60)} (due {t.due:%m-%d})" for t in overdue]}
        if failed:
            out["warning"] = (f"Could not read: {', '.join(failed)}. Say so, and don't call any time free or a day "
                              "light until it can be read.")
        out["next"] = "To propose work blocks: take them from free, then pass them to check_plan before you show them."
        out["rules"] = (f"work {rules['day_start']}-{rules['day_end']}, a {rules['break_minutes']} min break around "
                        f"every block, at most {rules['max_focus_hours']:g} h of planned work a day, nothing in the "
                        f"{rules['before_class_minutes']} min before a class, rest: {', '.join(rules['rest_days'])}, "
                        f"work tasks only: {', '.join(rules['work_only_days'])}")
        return out

    async def check_plan(self, blocks: list[dict]) -> dict:
        """Check proposed blocks [{task, start, end, work}] against the rules and the days they fall on."""
        rules = self.rules()
        parsed = []
        for b in blocks:
            try:
                s, e = parse_time(str(b["start"])), parse_time(str(b["end"]))
            except (KeyError, ValueError):
                return {"ok": False, "problems": [f"Bad block {b}: give start and end as YYYY-MM-DDTHH:MM."]}
            if e <= s:
                return {"ok": False, "problems": [f"Block for {b.get('task')}: end is not after start."]}
            parsed.append((s, e, str(b.get("task") or "work"), bool(b.get("work"))))
        if not parsed:
            return {"ok": False, "problems": ["No blocks given."]}
        first, last = min(p[0] for p in parsed).date(), max(p[1] for p in parsed).date()
        loaded, failed, tasks = await self.load(first, last)
        if failed:
            return {"ok": False, "problems": [f"Could not read {', '.join(failed)}: the plan can't be checked. Say so."]}
        days = {d.day: d for d in loaded}
        gap = timedelta(minutes=rules["break_minutes"])
        problems, per_day = [], {}
        named = {p[2]: find_task(tasks, p[2])[0] for p in parsed}
        for s, e, name, work in parsed:
            day, wd, label = days[s.date()], DAYS[s.weekday()], f"{name} {DAYS[s.weekday()]} {s:%m-%d} {hm(s)}-{hm(e)}"
            if wd in rules["rest_days"]:
                problems.append(f"{label}: {wd} is a rest day.")
            if wd in rules["work_only_days"] and not work:
                problems.append(f"{label}: {wd} is for work tasks only (pass work: true if this is work).")
            if hm(s) < rules["day_start"] or (hm(e) > rules["day_end"] and e.date() == s.date()):
                problems.append(f"{label}: outside {rules['day_start']}-{rules['day_end']}.")
            for ts, te, what in self.taken(day, rules, skip_task=named[name]):
                if s < te and ts < e:
                    problems.append(f"{label}: overlaps {what} ({hm(ts)}-{hm(te)}).")
                elif s < te + gap and ts - gap < e:
                    problems.append(f"{label}: no {rules['break_minutes']} min break next to {what} ({hm(ts)}-{hm(te)}).")
            for ev in day.events:
                cs = ev["start"] - timedelta(minutes=rules["before_class_minutes"])
                if self.is_class(ev["title"], rules) and s < ev["start"] and e > cs and not (s < ev["end"] and ev["start"] < e):
                    problems.append(f"{label}: inside the {rules['before_class_minutes']} min before {ev['title']} "
                                    f"({hm(ev['start'])}).")
            for s2, e2, n2, _ in parsed:
                if (s2, e2, n2) != (s, e, name) and s2.date() == s.date() and s < e2 + gap and s2 - gap < e:
                    if s2 >= s:   # each pair once
                        problems.append(f"{label}: no {rules['break_minutes']} min break before {n2} at {hm(s2)}.")
            if (e - s).total_seconds() / 3600 > rules["max_block_hours"]:
                problems.append(f"{label}: longer than {rules['max_block_hours']:g} h; split it with a break.")
            per_day.setdefault(s.date(), []).append((s, e))
        for d, bl in per_day.items():
            others = [(p["start"], p["end"]) for p in days[d].planned if p["task"] not in named.values()]
            total = hours(bl) + hours(others)
            if total > rules["max_focus_hours"]:
                problems.append(f"{DAYS[d.weekday()]} {d:%m-%d}: {total:g} h of planned work, over the "
                                f"{rules['max_focus_hours']:g} h a day. Move or drop something.")
            fixed = hours([(ev["start"], ev["end"]) for ev in days[d].events] + days[d].busy)
            if total + fixed > rules["max_day_hours"]:
                problems.append(f"{DAYS[d.weekday()]} {d:%m-%d}: {total:g} h of work plus {fixed:g} h of meetings and "
                                f"classes is over {rules['max_day_hours']:g} h for the day. Plan less.")
        for name, t in named.items():
            if re.search(r"\bprep\b", name, re.I) and self.is_class(name, rules):
                got = hours((s, e) for s, e, n, _ in parsed if n == name)
                if got < rules["class_prep_hours"]:
                    problems.append(f"{name}: {got:g} h planned; class prep needs at least {rules['class_prep_hours']:g} h.")
        return {"ok": not problems, "problems": problems,
                "planned_hours_per_day": {f"{DAYS[d.weekday()]} {d:%m-%d}": hours(bl) for d, bl in per_day.items()}}

    async def workload(self, days: int = 14) -> dict:
        """For each open task due in the next days: the hours it still needs against the free focus hours left
        before its due date (shared with the tasks due before it)."""
        today = self.now().date()
        days = max(1, min(int(days or 14), 28))
        loaded, failed, tasks = await self.load(today, today + timedelta(days=days - 1))
        rules = self.rules()
        if failed:
            return {"warning": f"Could not read {', '.join(failed)}: free time is unknown. Say so."}
        free_by_day = {}
        for d in loaded:
            focus = hours((p["start"], p["end"]) for p in d.planned)
            free_by_day[d.day] = max(0.0, min(rules["max_focus_hours"] - focus, hours(self.free(d, rules))))
        due = sorted((t for t in tasks if not t.done and t.due and today <= t.due < today + timedelta(days=days)),
                     key=lambda t: t.due)
        rows, need_so_far, no_est = [], 0.0, []
        for t in due:
            if t.est is None:
                no_est.append(f"{short(t.title, 60)} (due {t.due:%m-%d})")
                continue
            future_plan = hours((s, e) for s, e in t.plan if s >= self.now())
            need = max(0.0, t.est - future_plan)
            need_so_far += need
            free = round(sum(v for d, v in free_by_day.items() if d <= t.due), 2)
            rows.append({"task": short(t.title, 60), "due": f"{DAYS[t.due.weekday()]} {t.due:%m-%d}", "estimate_h": t.est,
                         "planned_ahead_h": future_plan, "unplanned_h": need,
                         "free_focus_h_until_due": free, "at_risk": need_so_far > free})
        out = {"tasks": rows}
        if no_est:
            out["no_estimate"] = no_est
            out["note"] = "Estimate these (read the email or file first; ask if unsure) and save est: Nh on their lines."
        if any(r["at_risk"] for r in rows):
            out["warning"] = "Some tasks don't fit before their due date: tell the user early, and propose what to move or drop."
        return out

    async def plan_block(self, key: str | None, args: dict) -> types.CallToolResult:
        action = str(args.get("action") or "add")
        query = str(args.get("task") or "")
        if self.guard and (refused := self.guard(key, "plan_block", args)):
            return text_result(refused, True)
        async with self.write_lock:
            text = self.tasks_path.read_text() if self.tasks_path.exists() else ""
            tasks = parse_tasks(text, self.now().date())
            try:
                old = (parse_time(args["old_start"]), parse_time(args["old_end"])) if args.get("old_start") else None
                new = (parse_time(args["start"]), parse_time(args["end"])) if action != "remove" else None
            except (KeyError, ValueError):
                return text_result("Give times as YYYY-MM-DDTHH:MM (start, end; old_start and old_end to move).", True)
            task, hits = find_task(tasks, query)
            if not task and len(hits) > 1:   # same-named to-dos (a gym week): the one due on the block's day
                day = (old or new or (parse_time(args["start"]), None) if args.get("start") else None)
                on = [t for t in hits if day and t.due == day[0].date()]
                task = on[0] if len(on) == 1 else None
            if not task:
                names = "; ".join(short(t.title, 60) for t in hits[:5]) or "none"
                return text_result(f"No single open task matches {query!r} (close: {names}). Add the task to Tasks.md "
                                   "first, or name it more exactly.", True)
            if action == "remove":
                old = old or ((parse_time(args["start"]), parse_time(args["end"])) if args.get("start") else None)
                if not old:
                    return text_result("Give the block to remove (start and end).", True)
            if action == "move" and not old:
                return text_result("Give old_start and old_end of the block to move.", True)
            title = str(args.get("title") or short(task.title, 60))
            email = self.calendar_email()
            done = []
            if old:
                ev = await self.find_event(email, old, title, task)
                if ev:
                    r = await self.google_call("manage_event", {"user_google_email": email, "action": "delete",
                                                                "event_id": ev})
                    if r.is_error:
                        return text_result("Could not delete the old event: " + self._text(r), True)
                    done.append("deleted the old event")
                else:
                    done.append("found no calendar event for the old block")
            if new:
                r = await self.google_call("manage_event", {
                    "user_google_email": email, "action": "create", "summary": title,
                    "start_time": new[0].isoformat(), "end_time": new[1].isoformat(),
                    "description": f"Work block for: {short(task.title, 200)} (Milo)"})
                if r.is_error:
                    return text_result("Could not create the event: " + self._text(r) + ". Tasks.md is unchanged.", True)
                done.append("created the event")
            plan = [b for b in task.plan if not (old and abs((b[0] - old[0]).total_seconds()) < 60)]
            if new:
                plan.append(new)
            lines = text.splitlines()
            line = task.raw
            moved_due = bool(old and new and task.due == old[0].date() and len(task.parts) > 1)
            if moved_due:   # a session due on its own block's day: its day moves with the block
                parts = line.split(" | ")
                parts[1] = re.sub(r"^\s*\d{4}-\d{2}-\d{2}", new[0].date().isoformat(), parts[1])
                line = " | ".join(parts)
                done.append(f"moved its due date to {new[0]:%m-%d} (it was the old block's day; say if it is a real deadline)")
            lines[task.line] = set_plan(line, plan)
            self.tasks_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
        when = (f"{DAYS[new[0].weekday()]} {new[0]:%m-%d} {hm(new[0])}-{hm(new[1])}" if new else "")
        return text_result(f"{', '.join(done).capitalize()} on {email}; the task line in Tasks.md now says "
                           f"{lines[task.line].split(' | ')[-1] if plan else 'no plan'}." + (f" Block: {when}." if when else ""))

    def calendar_email(self) -> str:
        want = str(self.rules()["default_calendar"]).lower()
        accts = self.accounts()
        hit = next((a for a in accts if want in (a.get("label", "").lower(), a["email"].lower())), None)
        return (hit or accts[0])["email"]

    async def find_event(self, email: str, block: tuple[datetime, datetime], title: str, task: Task) -> str | None:
        r = await self.google_call("get_events", {"user_google_email": email, "calendar_id": "primary",
                                                  "time_min": (block[0] - timedelta(minutes=1)).isoformat(),
                                                  "time_max": (block[1] + timedelta(minutes=1)).isoformat()})
        best = None
        for m in EVENT_LINE.finditer(self._text(r)):
            if "T" not in m["start"] or not m["id"]:
                continue
            if abs((parse_time(m["start"]) - block[0]).total_seconds()) < 60:
                if words(m["title"]) & (words(title) | words(task.title)):
                    return m["id"]
                best = best or m["id"]
        return best

    @staticmethod
    def _text(r: types.CallToolResult) -> str:
        return " ".join(c.text for c in r.content if isinstance(c, types.TextContent))

    # MCP handlers

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def _call_tool(self, ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        args = dict(params.arguments or {})
        key = ctx.request.query_params.get("k") if ctx.request is not None else None
        return await self.call(params.name, args, key)

    async def call(self, name: str, args: dict, key: str | None = None) -> types.CallToolResult:
        try:
            if name == "day_view":
                out = await self.day_view(args.get("start"), args.get("days") or 1)
            elif name == "check_plan":
                out = await self.check_plan(list(args.get("blocks") or []))
            elif name == "workload":
                out = await self.workload(args.get("days") or 14)
            elif name == "plan_block":
                return await self.plan_block(key, args)
            else:
                return text_result(f"No tool {name}.", True)
        except ValueError as e:
            return text_result(f"Bad input: {e}", True)
        except Exception as e:
            log.exception("planner %s", name)
            return text_result(f"The planner failed ({type(e).__name__}: {e}).", True)
        return text_result(json.dumps(out, ensure_ascii=False, indent=1))


BLOCK = {"type": "object", "properties": {
    "task": {"type": "string", "description": "The to-do the block is for, as named in Tasks.md"},
    "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM, local time"},
    "end": {"type": "string", "description": "YYYY-MM-DDTHH:MM, local time"},
    "work": {"type": "boolean", "description": "true for a work (job) task: allowed on work-only days"}},
    "required": ["task", "start", "end"]}
TOOLS = [
    types.Tool(name="day_view", description=(
        "The user's days in one read: events from all their Google calendars, their work meetings (busy.json, no "
        "titles), the work blocks planned in Tasks.md, what is due, overdue items, the free time left for work under "
        "their planning rules, and the focus hours left. Use it before you answer anything about a day or a week, "
        "and before you plan. If it says a source failed, say so and don't call time free."),
        input_schema={"type": "object", "properties": {
            "start": {"type": "string", "description": "First day, YYYY-MM-DD (default today)"},
            "days": {"type": "integer", "minimum": 1, "maximum": 14, "description": "How many days (default 1)"}}}),
    types.Tool(name="check_plan", description=(
        "Check proposed work blocks against the user's planning rules (working hours, breaks, nothing in meetings or "
        "just before class, a cap on work hours a day, rest and work-only days, class prep size). Call it on every "
        "plan before you show it, fix every problem it reports, and check again. Existing blocks of the same task "
        "are treated as replaced."),
        input_schema={"type": "object", "properties": {"blocks": {"type": "array", "items": BLOCK}},
                      "required": ["blocks"]}),
    types.Tool(name="workload", description=(
        "For each open task due in the next days: its estimate, what is planned, and whether it fits in the free "
        "work hours before its due date. Use it when a task with a size or a deadline is added, in weekly planning, "
        "and when a day looks full. Lists tasks with no estimate."),
        input_schema={"type": "object", "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": 28, "description": "How far ahead (default 14)"}}}),
    types.Tool(name="plan_block", description=(
        "Add, move or remove a work block for a to-do: it changes the calendar event and the task's plan: in "
        "Tasks.md together, so they never disagree. Only after the user agreed to that block in this chat. Check the "
        "block with check_plan first."),
        input_schema={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["add", "move", "remove"]},
            "task": {"type": "string", "description": "The to-do, as named in Tasks.md"},
            "start": {"type": "string", "description": "New block start, YYYY-MM-DDTHH:MM (remove: the block's start)"},
            "end": {"type": "string", "description": "New block end (remove: the block's end)"},
            "old_start": {"type": "string", "description": "move: the old block's start"},
            "old_end": {"type": "string", "description": "move: the old block's end"},
            "title": {"type": "string", "description": "Event title (default: the task's short title)"}},
            "required": ["action", "task"]}),
]


def PlannerMCPApp(tools: PlannerTools) -> BearerEndpoint:
    return BearerEndpoint(tools.manager, tools.key)
