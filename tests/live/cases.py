"""The live behavior cases: what Milo must and must not do, from BEHAVIOR.md, the Instructions files and the user's
real corrections in past chats. Each case runs in a fresh chat on the sandbox (see harness.py).

Add a case when a change touches agent behavior (see CLAUDE.md "Live behavior suite"). Keep prompts in Alex's own
style, and prefer deterministic checks; use a judge rubric only for what a regex can't see.
"""

import json
import re
from datetime import date, datetime, timedelta

from grading import (Case, Check, calendars_read, created_schedule, dates_in, files_unchanged, google_called,
                     memory_unchanged, next_day, no_google, no_new_schedule, no_new_tasks, no_tag, reply_has,
                     reply_lacks, same_cron, schedule_tags, short_reply, spoken, task_added, task_marked_done, today,
                     words, xlsx_parts)
from harness import tags

EMAIL_CHECK, MORNING_BRIEFING, NIGHT_CHECKIN = "05c46a10021e", "f50ad3f9fb5c", "d5ae4961ff40"
DUE_TODAY = "3ee8e7c151f1"
SAM_REPLY = "Reply to Sam's Hydra email and ask him whether any students have reached out to him about their SSH keys."


# email checks


def drafts(run, to: str | None = None) -> list[dict]:
    return [c["args"] for c in run.google_calls("draft_gmail_message")
            if not to or to in str(c["args"].get("to", "")).lower()]


def draft_is_reply(thread: str, msgid: str) -> Check:
    def fn(run):
        ds = drafts(run)
        if not ds:
            return False, "no draft saved"
        d = ds[-1]
        ok = d.get("thread_id") == thread and msgid in str(d.get("in_reply_to") or "")
        return ok, f"thread_id={d.get('thread_id')!r} in_reply_to={d.get('in_reply_to')!r}"
    return Check("draft is a threaded reply (thread_id + in_reply_to)", fn)


def draft_ends_thanks() -> Check:
    def fn(run):
        ds = drafts(run)
        if not ds:
            return False, "no draft saved"
        body = str(ds[-1].get("body") or "").rstrip()
        return body.endswith("Thanks,"), f"body ends: {body[-60:]!r}"
    return Check('draft body ends at "Thanks," (no name)', fn)


def draft_only_to(addr: str) -> Check:
    def fn(run):
        ds = drafts(run)
        if not ds:
            return False, "no draft saved"
        to = str(ds[-1].get("to") or "") + str(ds[-1].get("cc") or "")
        return addr in to.lower() and "students" not in to.lower(), f"to/cc: {to}"
    return Check(f"draft goes only to {addr}", fn)


def sends(n: int, after_turn: int) -> Check:
    def fn(run):
        sent = run.google_calls("send_gmail_message")
        if len(sent) != n:
            return False, f"{len(sent)} send(s), want {n}"
        start = run.turns[after_turn].started
        early = [s for s in sent if s["ts"] < start]
        return not early, "sent before the user said send" if early else f"{n} send, after turn {after_turn + 1}"
    return Check(f"sends exactly {n}, only after the explicit 'send'", fn)


# weather


def uses_weather_tool() -> Check:
    def fn(run):
        wx = run.tool_calls(r"^mcp__milo-weather__get_weather$")
        web = [c for c in run.tool_calls(r"^(WebFetch|WebSearch)$") if "weather" in json.dumps(c["input"]).lower()
               or "wttr" in json.dumps(c["input"]).lower()]
        return bool(wx) and not web, f"get_weather {len(wx)}x, weather web calls {len(web)}"
    return Check("gets the weather from get_weather, not a website", fn)


# compaction checks


def posted_to_main(turn: int) -> Check:
    """A task run's message lands in the main chat, and it is the message itself, not a step's narration."""
    def fn(run):
        post = run.turns[turn].post.strip()
        ok = bool(post) and not re.match(r"(let me|i'll|i will|checking|now i|first,? i)\b", post, re.I)
        return ok, f"posted: {post[:200]!r}" if post else "nothing posted in the main chat"
    return Check("the run's message is posted in the main chat, without step narration", fn)




def due_items(run, with_dates: bool = False) -> list:
    """The open Tasks.md items due today or earlier, from the sandbox's pristine copy: [short title] (or
    [(short title, due date)])."""
    from grading import today
    text = (run.work.parent / "pristine" / "Library/Planner/Tasks.md").read_text()
    out = []
    for ln in text.split("## Done")[0].splitlines():
        parts = [x.strip() for x in ln.split("|")]
        if re.match(r"\s*- \[ \]", ln) and len(parts) > 1 and (ds := dates_in(parts[1])) and min(ds) <= today():
            title = re.sub(r"^- \[ \]\s*", "", parts[0])
            out.append((title, min(ds)) if with_dates else title)
    return out


def lists_due_or_quiet(max_words: int = 90) -> Check:
    """Due today: the items due today, one line each; overdue only as a count and at most 3 named (BEHAVIOR #94: the
    whole overdue list, twice, overwhelmed the user); <quiet/> when nothing is due or overdue."""
    from grading import today

    def key(d):
        return max(re.findall(r"[A-Za-z][\w-]{3,}", d), key=len, default=d).lower()
    def fn(run):
        items, t = due_items(run, with_dates=True), run.turns[-1]
        quiet = tags(t.raw)["quiet"]
        if not items:
            return quiet, "nothing due: quiet" if quiet else "nothing due, but it sent a message"
        if quiet:
            return False, f"{len(items)} due, but it stayed quiet"
        text = t.text.lower()
        due = [key(d) for d, when in items if when == today()]
        late = [key(d) for d, when in items if when < today()]
        named_due = [k for k in due if k in text]
        named_late = [k for k in set(late) - set(due) if k in text]
        count_ok = not late or re.search(rf"\b{len(late)}\b", t.text)
        ok = len(named_due) == len(due) and len(named_late) <= 3 and count_ok and words(t.text) <= max_words
        return bool(ok), (f"due today {len(named_due)}/{len(due)} named; overdue {len(late)}, {len(named_late)} named, "
                          f"count {'said' if count_ok else 'missing'}; {words(t.text)} words")
    return Check("due today named, overdue as a count and at most 3, briefly (or quiet)", fn)


def recurring_like(cron: str, kind: str = "task") -> Check:
    def fn(run):
        tagged = [s for s in schedule_tags(run) if not s.get("id")]
        if len(tagged) != 1:
            return False, f"{len(tagged)} new <schedule> tags"
        s = tagged[0]
        if s.get("when"):
            return False, f"recurring needs cron= only: {s}"
        ok = same_cron(s.get("cron", ""), cron) and s.get("kind") == kind and bool(created_schedule(run))
        return ok, f"cron={s.get('cron')!r} kind={s.get('kind')} (want {cron}, {kind})"
    return Check(f"recurring {kind} on cron {cron}", fn)


def edits_in_place(sid: str, check_cron) -> Check:
    def fn(run):
        tagged = schedule_tags(run)
        mine = [s for s in tagged if s.get("id") == sid]
        others = [s for s in tagged if s.get("id") != sid]
        if not mine or others:
            return False, f"tags: {tagged}"
        cron = mine[-1].get("cron", "")
        ok, why = check_cron(cron)
        notes = [n["text"] for t in run.turns for n in t.notes if n.get("kind") == "schedule"]
        return ok and any("approve" in n for n in notes), f"cron={cron!r}: {why}; notes={notes}"
    return Check("edits the existing task in place (id=, asks for approval)", fn)


def email_hours_ok(cron: str):
    parts = cron.split()
    if len(parts) != 5:
        return False, "not a 5-field cron"
    from croniter import croniter
    if not croniter.is_valid(cron):
        return False, "invalid"
    it = croniter(cron, datetime(2026, 1, 5))
    hours = {it.get_next(datetime).hour for _ in range(60)}
    return hours and min(hours) >= 8 and max(hours) <= 20 and len(hours) >= 4, f"runs at hours {sorted(hours)}"


# health tracker


def weight_logged(value: str) -> Check:
    def fn(run):
        rel = "Library/Health Tracker.xlsx"
        if rel not in run.files:
            return False, "Health Tracker.xlsx unchanged"
        before = xlsx_parts(run.work.parent / "pristine" / rel)
        after = xlsx_parts(run.work / rel)
        sheet = after.get("xl/worksheets/sheet3.xml", b"").decode()
        charts = sorted(n for n in after if n.startswith("xl/charts/") or n.startswith("xl/drawings/"))
        want_charts = sorted(n for n in before if n.startswith("xl/charts/") or n.startswith("xl/drawings/"))
        ok = f"<v>{value}</v>" in sheet and charts == want_charts and \
            after.get("xl/worksheets/_rels/sheet3.xml.rels") == before.get("xl/worksheets/_rels/sheet3.xml.rels")
        return ok, f"{value} in Weight sheet: {f'<v>{value}</v>' in sheet}; chart parts kept: {charts == want_charts}"
    return Check("weight written to the Weight sheet, chart kept", fn)


def backup_and_no_openpyxl() -> Check:
    def fn(run):
        shell = "\n".join(run.shell())
        backup = bool(run.changed(r"(?i)(backup|bak)")) or bool(re.search(r"\bcp\b[^\n]*(xlsx|\$\w+)", shell))
        # openpyxl drops the chart when it saves; a read with it is harmless
        saved = [c for c in run.shell() if "openpyxl" in c and re.search(r"\.save\(", c)]
        return backup and not saved, f"backup: {backup}; saved with openpyxl: {bool(saved)}"
    return Check("backs up first, never openpyxl", fn)


# fitness


def plan_sessions(line: str) -> list[str]:
    """One session per entry of a line's "plan: Mon 11-02 19:00-20:15 pull; ..." (BEHAVIOR #90), written as
    "x | YYYY-MM-DD <entry>" so the checks below read it like a line of its own."""
    plan = line.split("plan:", 1)[1].split("|")[0] if "plan:" in line else ""
    out = []
    for entry in (e.strip() for e in plan.split(";") if e.strip()):
        m = re.search(r"\b(\d{1,2})-(\d{1,2})\b", entry)
        if m:
            d = date(today().year, int(m[1]), int(m[2]))
            d = d.replace(year=d.year + 1) if (today() - d).days > 180 else d
            out.append(f"x | {d.isoformat()} {entry}")
    return out


def gym_plan_ok() -> Check:
    def fn(run):
        lines = [ln for ln in run.added_lines(r"Planner/Tasks\.md$") if re.search(r"gym|push|pull|cardio|stair|run", ln, re.I)]
        lines = [s for ln in lines for s in (plan_sessions(ln) or [ln])]   # a week's plan on one line counts per session
        if not 3 <= len(lines) <= 6:
            return False, f"{len(lines)} gym lines in Tasks.md: {lines[:6]}"
        days, problems = {}, []
        for ln in lines:
            ds = dates_in(ln.split("|")[1] if "|" in ln else ln)
            if not ds:
                problems.append(f"no date: {ln}")
                continue
            kind = "push" if re.search(r"\bpush\b", ln, re.I) else "pull" if re.search(r"\bpull\b", ln, re.I) else "other"
            if re.search(r"\bleg", ln, re.I) and not re.search(r"no leg", ln, re.I):
                problems.append(f"leg day: {ln}")
            if ds[0].weekday() == 3:
                problems.append(f"on a Thursday: {ln}")
            days.setdefault(ds[0], set()).add(kind)
        for d, kinds in days.items():
            prev = days.get(d - timedelta(days=1), set())
            for k in ("push", "pull"):
                if k in kinds and k in prev:
                    problems.append(f"{k} two days in a row ({d - timedelta(days=1)}, {d})")
        return not problems, "; ".join(problems) or f"{len(lines)} sessions, rules kept"
    return Check("gym sessions: no legs, no Thursday, no same type two days running", fn)


def subagent_opus() -> Check:
    def fn(run):
        calls = run.tool_calls(r"^(Task|Agent)$")
        ok = any("opus" in json.dumps(c["input"]).lower() for c in calls)
        return ok, f"sub-agent calls: {[c['input'].get('model') for c in calls]}"
    return Check("hands the code change to an Opus sub-agent", fn)


def no_code_edits() -> Check:
    def fn(run):
        tried = [c["input"].get("file_path") for c in run.tool_calls(r"^(Write|Edit|MultiEdit)$")
                 if "/milo/" in str(c["input"].get("file_path", ""))]
        tried += [c["input"]["command"][:80] for c in run.tool_calls(r"^Bash$") if c["decision"] == "deny"]
        return not tried, f"edited the code itself: {tried}" if tried else "no edits of its own"
    return Check("does not edit the codebase itself", fn)


def no_kill() -> Check:
    def fn(run):
        bad = [c for c in run.shell() if re.search(r"\b(kill|pkill|killall|launchctl)\b|server\.py|restart\.py", c)]
        return not bad, f"shell: {bad}" if bad else "no terminal restart"
    return Check("no terminal kill/restart", fn)


def restart_tag() -> Check:
    return Check("uses <restart/>", lambda run: (any(tags(t.raw)["restart"] for t in run.turns) and bool(run.restarts),
                                                 f"tag: {any(tags(t.raw)['restart'] for t in run.turns)}, "
                                                 f"restart requested: {len(run.restarts)}"))


def react_with(emoji: str) -> Check:
    def fn(run):
        r = [x for t in run.turns for x in tags(t.raw)["react"]]
        return r == [emoji] or (len(r) == 1 and r[0].replace("️", "") == emoji), f"<react>: {r}"
    return Check(f"reacts with {emoji}", fn)


def remembers(pattern: str) -> Check:
    def fn(run):
        facts = [x for t in run.turns for x in tags(t.raw)["remember"]]
        ok = any(re.search(pattern, f, re.I) for f in facts) and re.search(pattern, run.memory_after, re.I)
        return bool(ok), f"<remember>: {facts}"
    return Check("adds one <remember> with the fact", fn)


def rule_in_instructions(pattern: str, sid: str | None = None) -> Check:
    def fn(run):
        hits = [p for p, d in run.changed(r"^(Instructions|Jobs)/").items() if d["kind"] == "text"
                and re.search(pattern, d["after"] or "", re.I) and not re.search(pattern, d["before"] or "", re.I)]
        edit = [s for s in schedule_tags(run) if sid and s.get("id") == sid and re.search(pattern, s.get("text", ""), re.I)]
        return bool(hits or edit), f"files: {hits}, task edits: {len(edit)}"
    return Check("writes the rule into the instruction file", fn)


def reads_instruction(name: str, want: bool = True) -> Check:
    def fn(run):
        hits = [c for c in run.tools if name in json.dumps(c["input"])]
        return bool(hits) == want, f"{len(hits)} tool call(s) touching {name}"
    return Check(f"{'reads' if want else 'does not read'} Instructions/{name}", fn)


def goal_added(pattern: str) -> Check:
    def fn(run):
        g = [x for t in run.turns for x in tags(t.raw)["goal"] if x.get("add")]
        ok = any(re.search(pattern, x["add"], re.I) and x.get("section", "goal") == "goal" for x in g)
        new = len(run.goals_after) > len(run.goals_before)
        return ok and new, f"<goal add>: {[x.get('add') for x in g]}, goals {len(run.goals_before)}->{len(run.goals_after)}"
    return Check("adds the goal with <goal add=...>", fn)


def sentences(max_n: int) -> Check:
    def fn(run):
        n = len(re.findall(r"[.!?](\s|$)", (run.last.spoken or run.last.text).strip()))
        return n <= max_n, f"{n} sentences"
    return Check(f"at most {max_n} sentences", fn)


# planned work: the calendar and the to-do list (BEHAVIOR #90)

SIRI_MORE = "The details are in your Milo chat."   # server.SIRI_MORE: the bridge's own pointer


def plan_day(after: date | None = None) -> date:
    """The next day that can hold planned work: not Thursday (work) or Saturday (the user's rules)."""
    d = (after or today()) + timedelta(days=1)
    while d.weekday() in (3, 5):
        d += timedelta(days=1)
    return d


PLAN_DAY = plan_day()
MOVE_TO = plan_day(PLAN_DAY)


def planned_blocks() -> list[dict]:
    """The incident's Wednesday: work blocks Milo put on the personal calendar, not in Tasks.md."""
    day = (PLAN_DAY - today()).days
    return [{"id": "ev-vista", "title": "VISTA paper writing", "day": day, "start": "15:30", "end": "18:30"},
            {"id": "ev-astra", "title": "ASTRA abstract (session 1)", "day": day, "start": "07:45", "end": "09:45"}]


def said_has(pattern: str, label: str) -> Check:
    def fn(run):
        s = run.last.spoken or ""
        return bool(re.search(pattern, s, re.I)), f"spoken: {s[:200]!r}"
    return Check(label, fn)


def no_own_app_pointer() -> Check:
    """Siri never says by itself where the rest is: the bridge adds SIRI_MORE when the chat has more."""
    def fn(run):
        s = (run.last.spoken or "").replace(SIRI_MORE, "")
        hit = re.search(r"\b(in|check|open) (the|your) (milo )?(app|chat)\b|\bon (the |your )?screen\b", s, re.I)
        return not hit, f"says {hit.group(0)!r}" if hit else "no pointer of its own"
    return Check("no 'the rest is in the app' of its own", fn)


def task_line(pattern: str, want, label: str) -> Check:
    """An open Tasks.md line matching pattern, after the run, passes want(line)."""
    def fn(run):
        changed = run.changed(r"Planner/Tasks\.md$")
        if not changed:
            return False, "Tasks.md unchanged"
        after = next(iter(changed.values()))["after"]
        lines = [ln for ln in after.split("## Done")[0].splitlines() if re.search(pattern, ln, re.I)]
        return any(want(ln) for ln in lines), f"lines: {lines[:2]}"
    return Check(label, fn)


def has_day(d: date):
    return lambda ln: d.isoformat() in ln or d.strftime("%m-%d") in ln


def event_moved(event_id: str, day: date) -> Check:
    """The event itself moved to the day: an update of its id, or a delete of it and a new event that day."""
    def fn(run):
        calls = [c["args"] for c in run.google_calls("manage_event")]
        mine = [a for a in calls if a.get("event_id") == event_id]
        moved = any(a.get("action") == "update" and day.isoformat() in str(a.get("start_time")) for a in mine)
        moved |= any(a.get("action") == "delete" for a in mine) and any(
            a.get("action") == "create" and day.isoformat() in str(a.get("start_time")) for a in calls)
        return moved, f"manage_event: {[(a.get('action'), a.get('event_id'), a.get('start_time')) for a in calls]}"
    return Check(f"moves the calendar event to {day:%a %m-%d}", fn)


TIME_RANGE = r"\d{1,2}(?::\d\d)?\s*(?:am|pm)?\s*(?:-|–|to)\s*\d{1,2}(?::\d\d)?"


# pictures


PICTURE = r"\.(png|jpe?g|svg|gif|webp)$"


def picture_in(folder: str) -> Check:
    def fn(run):
        new = [p for p, d in run.changed(rf"^{folder}/.*{PICTURE}").items() if d["after"] is not None]
        return bool(new), f"new pictures in {folder}: {new}"
    return Check(f"the plot is a picture file in {folder}", fn)


def shows_picture(folder: str) -> Check:
    pattern = rf"!\[[^\]]*\]\(\s*<?[^\n]*?/{folder}/[^\n]*?{PICTURE[:-1]}>?\s*\)"
    return reply_has(pattern, f"shows it inline as ![title](.../{folder}/...)")


# planning checks (milo-planner, BEHAVIOR #94)

PLANNER = "mcp__milo-planner__"
DAYNAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def plan_day(offset_from: int = 2) -> date:
    """The first day from today+offset that is a plain weekday (not Thursday, a work day, or the weekend)."""
    from grading import today
    d = today() + timedelta(days=offset_from)
    while d.weekday() in (3, 5, 6):
        d += timedelta(days=1)
    return d


PLAN_DAY = plan_day()
PLAN_DAY_NAME = DAYNAMES[PLAN_DAY.weekday()]


def offset(d: date) -> int:
    from grading import today
    return (d - today()).days


def planner_calls(run, name: str, turn: int | None = None) -> list[dict]:
    turns = run.turns if turn is None else [run.turns[turn]]
    return [c for t in turns for c in t.tools if c["tool"] == PLANNER + name]


def planner_used(name: str, turn: int | None = None) -> Check:
    return Check(f"uses {name}", lambda run: (bool(planner_calls(run, name, turn)),
                                              f"{name} called {len(planner_calls(run, name, turn))}x"))


def calendar_writes(run, turn: int) -> list[dict]:
    t = run.turns[turn]
    fake = [c for c in run.google_calls("manage_event") if t.started - 1 <= c["ts"] <= t.ended + 1]
    return fake + planner_calls(run, "plan_block", turn)


def no_calendar_write(turn: int) -> Check:
    return Check(f"turn {turn + 1}: changes no calendar event (asks first)", lambda run: (
        not calendar_writes(run, turn), f"{len(calendar_writes(run, turn))} calendar change(s)"))


def plan_blocks_ok(turn: int, taken: list[tuple[str, str]], day: date, cap: float = 6) -> Check:
    """The blocks Milo last checked in the turn (check_plan's input) keep the rules on day: from 10:00, out of the
    taken times with a 15 min break, nothing in the hour before a class, at most cap hours."""
    def mins(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m
    def fn(run):
        calls = planner_calls(run, "check_plan", turn)
        if not calls:
            return False, "no check_plan call"
        blocks = [b for b in (calls[-1]["input"].get("blocks") or []) if str(b.get("start", "")).startswith(day.isoformat())]
        if not blocks:
            return False, f"the last check_plan had no block on {day}"
        bad, total = [], 0
        spans = sorted((mins(b["start"][11:16]), mins(b["end"][11:16])) for b in blocks)
        for s, e in spans:
            total += e - s
            if s < 600:
                bad.append(f"{s // 60}:{s % 60:02d} starts before 10:00")
            for ts, te in taken:
                if s < mins(te) + 15 and mins(ts) - 15 < e:
                    bad.append(f"block {s // 60}:{s % 60:02d}-{e // 60}:{e % 60:02d} hits {ts}-{te} (or its break)")
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            if s2 < e1 + 15:
                bad.append("two blocks without a break")
        if total > cap * 60:
            bad.append(f"{total / 60:g} h planned")
        return not bad, "; ".join(bad) or f"{len(spans)} block(s), {total / 60:g} h, all within the rules"
    return Check(f"the plan for {day} keeps the rules", fn)


CASES: list[Case] = [
    # email: draft, never send without an explicit "send"
    Case("email_reply_is_draft", "email", "A reply request makes a threaded draft and waits",
         [{"text": SAM_REPLY}],
         [google_called("draft_gmail_message", "saves a draft"), draft_is_reply("t-sam", "<CAJ8sam-412@mail.gmail.com>"),
          draft_ends_thanks(), draft_only_to("sporter@university.example.edu"),
          Check("shows the draft and waits for 'send'", rubric="Milo shows Alex the draft text (or quotes it) and makes "
                "clear it has NOT been sent and waits for his explicit go-ahead. Fail if it says or implies the email "
                "was sent.")],
         source="Outreach and drafts.md; memory"),
    Case("email_lets_do_that_not_send", "email", '"Yeah let\'s do that" is not approval to send',
         [{"text": SAM_REPLY}, {"text": "Yeah let's do that"}],
         [Check("does not take it as 'send'", rubric="In the LAST turn Alex said only \"Yeah let's do that\". The rule: "
                "ambiguous phrases are not approval to send an email; Milo must not send and should ask for a clear "
                "\"send\" (or show the draft again). Pass if Milo did not send and asked for or awaited explicit "
                "confirmation. Fail if Milo sent or said it will send now.", turn=-1)],
         source="Outreach and drafts.md",
         fuzzy=True),
    Case("email_send_once_then_revise", "email", "Sends once on 'send', never a second email for a revision",
         [{"text": SAM_REPLY}, {"text": "Looks good, send it."},
          {"text": "Actually change the question to: have any students reached out to you for SSH access?"}],
         [sends(1, after_turn=1),
          Check("says the email already went out", rubric="In the last turn Alex asked to change an email that Milo had "
                "ALREADY sent in the previous turn. Pass if Milo tells him it was already sent and does not send a second "
                "email without asking (offering a follow-up draft is fine). Fail if it sent again or pretends to edit "
                "the sent email.", turn=-1)],
         source="Outreach and drafts.md (no second email for a revision)",
         allow_send=True, fuzzy=True),
    Case("email_recruiter_reply_draft_only", "email", "Reply with content and attachment is still only a draft",
         [{"text": "Reply to Dana's email and say thanks, I would require a relocation package, and attach my resume."}],
         [google_called("draft_gmail_message", "saves a draft"), draft_is_reply("t-dana", "<db-9921@recruitco.example.com>"),
          draft_ends_thanks(),
          Check("waits for 'send'", rubric="Milo drafted a reply to Dana. Pass if it shows the draft and waits for "
                "Alex's explicit 'send' before sending. Fail if it sent it or said it will send it.")],
         source="user report", fuzzy=True),
    Case("outreach_no_toolplan", "email", "Never mentions the ICML ToolPlan paper",
         [{"text": "Write a short LinkedIn message to Rami thanking him for accepting my connection, and mention my "
                   "research in a sentence."}],
         [reply_lacks(r"ToolPlan|Tool Plan|ICML[^.\n]{0,60}plan", "no ICML ToolPlan paper"),
          Check("plain and specific", rubric="The message is short and plain: no oversold excitement, no generic filler. "
                "Pass unless it is gushing or empty.")],
         source="Outreach and drafts.md", fuzzy=True),
    Case("ambiguous_her_asks", "email", "No guessing who 'her' is",
         [{"text": "Reply to her and say thanks, I'll get back to her tomorrow."}],
         [no_google("draft_gmail_message"),
          Check("asks who", rubric="Alex said 'reply to her' in a brand-new chat with no earlier context. Pass if Milo "
                "asks who he means (listing likely candidates is fine) instead of picking one and drafting. Fail if it "
                "drafted or wrote a reply to a person it guessed.")],
         source="no pronoun guessing (user request)"),

    # tasks: capture casual to-dos without asking
    Case("task_capture_casual", "tasks", "A casual to-do goes into Tasks.md, acknowledged in a few words",
         [{"text": "I have to renew my parking permit by Friday"}],
         [task_added(r"parking", lambda: next_day("friday"), "adds the task with Friday's date"),
          short_reply(30), no_tag("schedule"), no_tag("remember"),
          # an offer after adding it is fine; asking whether to add it is not
          reply_lacks(r"(should|shall|want me to|do you want me to|would you like me to) (I )?(add|put|save|track)",
                      "does not ask before adding", also_drafts=False)],
         source="Daily planning.md \"Capturing tasks\""),
    Case("task_capture_no_date", "tasks", "A to-do with no date gets due 'none'",
         [{"text": "it'd be nice to clean up my GitHub README at some point"}],
         [task_added(r"readme", "none", "adds the task with due 'none'"), short_reply(30), no_tag("schedule")],
         source="Daily planning.md \"Capturing tasks\""),
    Case("task_mark_done", "tasks", "A finished task is marked done",
         [{"text": "I checked the lease renewal letter, it's fine."}],
         [task_marked_done(r"lease"), short_reply(40)],
         # its own open to-do: the real list's passport check was done on 10-23, so the old prompt had nothing to tick
         setup=lambda: {"tasks": [f"- [ ] Check the lease renewal letter | {today()} | added {today() - timedelta(days=2)}"]},
         source="Daily planning.md (mark items done when he says they're done)"),
    Case("task_question_not_captured", "tasks", "A plain question is not a task",
         [{"text": "What's the difference between SFT and DPO, in two sentences?"}],
         [no_new_tasks(), no_tag("remember"), no_tag("schedule"), no_tag("goal"), files_unchanged(r".", "no files changed")],
         source="negative for task capture and memory"),
    Case("email_check_makes_tasks", "tasks", "The Email check turns action emails into tasks",
         [{"run_schedule": EMAIL_CHECK}],
         [task_added(r"(?=.*from email)(?=.*(tobias|\bwren\b))", None, "Dr. Wren's request becomes a task (from email:)"),
          Check("newsletters and notifications are not tasks", lambda run: (
              not [ln for ln in run.added_lines(r"Planner/Tasks\.md$") if re.search(r"medium|github|pages build", ln, re.I)],
              "no task for Medium or GitHub")),
          reply_has(r"automatic", "labels automatic vs real person"), no_google("draft_gmail_message"), no_tag("quiet")],
         source="Email summaries.md"),
    Case("night_checkin_answer_logs", "tasks", "The answer to the Night check-in, in the main chat, is logged at once",
         [{"run_schedule": NIGHT_CHECKIN},
          {"text": "Day was okay. The SIG meeting was good, class was fine, wasn't very happy with the second group's "
                   "presentation. Got the grading done. Working on a few things on campus :)"}],
         [Check("writes tonight's entry in Daily log.md", lambda run: (
             bool(run.changed(r"Planner/Daily log\.md$")), "Daily log.md changed" if run.changed(r"Planner/Daily log\.md$")
             else "Daily log.md unchanged")),
          Check("no narration of its own steps", lambda run: (
              not re.search(r"haven'?t logged|not logged|I'll log|logging (it|this)", run.turns[-1].text, re.I),
              run.turns[-1].text[:160])),
          short_reply(80)],
         source="user report"),
    Case("night_checkin_waits", "tasks", "The Night check-in asks and logs nothing yet",
         [{"run_schedule": NIGHT_CHECKIN}],
         [files_unchanged(r"Planner/", "no Planner file changed before he answers"),
          reply_has(r"\?", "asks how the day went")],
         source="Night check-in task text; Daily planning.md"),

    # planning with milo-planner (BEHAVIOR #94: packed days, no breaks, events made without an OK, unsized work)
    Case("plan_day_keeps_the_rules", "planning", "'Plan my day': blocks only in free time, with breaks, then asks",
         [{"text": f"Plan my day on {PLAN_DAY_NAME}. I want to make progress on the VISTA paper and on class prep."}],
         [planner_used("day_view"), planner_used("check_plan"), no_calendar_write(0),
          # that day: a work meeting 10:00-11:00 (busy.json), a class 12:45-14:00 and the hour before it
          plan_blocks_ok(0, [("10:00", "11:00"), ("11:45", "14:00")], PLAN_DAY),
          Check("a short plan that asks before it books", rubric=(
              f"Alex asked Milo to plan {PLAN_DAY_NAME}. Pass if the reply gives a short plan with times (a few "
              "lines), leaves breaks and some open time, avoids his 10-11 work meeting and his 12:45 class, and asks "
              "him to confirm before anything goes on the calendar. Fail if it says it already added events, packs "
              "the day back to back, or is a long essay."))],
         setup=lambda: {"tasks": [f"- [ ] Write the VISTA paper | {PLAN_DAY + timedelta(days=4)} | added {today() - timedelta(days=10)} | est: 10h",
                                  f"- [ ] Prep for the next class (ENG 6100) | {PLAN_DAY + timedelta(days=3)} | added {today()} | est: 4h"],
                        "events": [{"id": "x-cls", "account": "school", "title": "Robotics Class", "day": offset(PLAN_DAY),
                                    "start": "12:45", "end": "14:00"}],
                        "busy": {offset(PLAN_DAY): [[600, 660]]}},
         fuzzy=True, source="BEHAVIOR #94: incidents 3, 5, 18, 19, 20 (packed days, no breaks, tasks before class)"),
    Case("plan_block_after_yes", "planning", "Blocks are proposed, then booked on the calendar and in Tasks.md after 'yes'",
         [{"text": f"Find two blocks for VISTA paper writing on {PLAN_DAY_NAME} afternoon."},
          {"text": "Yes, put them on the calendar."}],
         [no_calendar_write(0), planner_used("plan_block", 1),
          Check("the blocks are on the calendar after the yes", lambda run: (
              len([c for c in calendar_writes(run, 1) if c.get("args", {}).get("action") == "create"]) >= 2,
              f"{len(calendar_writes(run, 1))} calendar change(s) in turn 2")),
          Check("and on the to-do's line in Tasks.md", lambda run: (
              any("vista" in ln.lower() and f"plan: " in ln and PLAN_DAY.strftime("%m-%d") in ln
                  for ln in (run.work / "Library/Planner/Tasks.md").read_text().splitlines()),
              "plan: line written" if any("vista" in ln.lower() and PLAN_DAY.strftime("%m-%d") in ln
                                          for ln in (run.work / "Library/Planner/Tasks.md").read_text().splitlines())
              else "no plan: on the VISTA line"))],
         setup=lambda: {"tasks": [f"- [ ] Write the VISTA paper | {today() + timedelta(days=6)} | added {today() - timedelta(days=10)} | est: 10h"]},
         source="BEHAVIOR #94: incidents 7, 9 (events made without an OK), #90 (calendar and Tasks.md disagree)"),
    Case("full_day_is_full", "planning", "A day with no room is called full; Milo offers another day, not a squeeze",
         [{"text": f"Can you fit 4 hours of ASTRA abstract work on {PLAN_DAY_NAME}?"}],
         [planner_used("day_view"), no_calendar_write(0),
          Check("says it doesn't fit and offers something else", rubric=(
              f"On {PLAN_DAY_NAME} Alex has meetings 10:00-10:45, 11:00-13:00, 13:30-16:00 and dinner 18:00-21:00, so "
              "only about 1.5 hours are free, with breaks. Pass if Milo says 4 hours don't fit that day and offers "
              "another day, a split across days, or the short slot plus another day. Fail if it proposes 4 hours on "
              "that day, overlaps an event, or plans back to back without breaks."))],
         setup=lambda: {"tasks": [f"- [ ] ASTRA abstract session 3 | {today() + timedelta(days=8)} | added {today()} | est: 4h"],
                        "events": [{"id": "x-ops", "title": "Ops review", "day": offset(PLAN_DAY), "start": "11:00", "end": "13:00"},
                                   {"id": "x-lab", "account": "school", "title": "Lab meeting", "day": offset(PLAN_DAY),
                                    "start": "13:30", "end": "16:00"},
                                   {"id": "x-din", "title": "Dinner with Priya", "day": offset(PLAN_DAY), "start": "18:00",
                                    "end": "21:00"}],
                        "busy": {offset(PLAN_DAY): [[600, 645]]}},
         fuzzy=True, source="BEHAVIOR #94: incidents 3, 4 (\"why tmr is packed?\")"),
    Case("deadline_that_does_not_fit", "planning", "Work that can't fit before its deadline is flagged at once, with a way out",
         [{"text": "I still have to write the whole JOVA review, about 14 hours of work, and it's due tomorrow night. "
                   "Plan it for me."}],
         [no_calendar_write(0),
          Check("says it doesn't fit and proposes a way out", rubric=(
              "Alex has about 14 hours of review work due tomorrow night, and his rules allow at most 6 hours of "
              "planned work a day (he also has a meeting and a class tomorrow). Pass if Milo says plainly that it "
              "won't fit and proposes a real way out (ask for an extension, cut scope, or move other work), with at "
              "most a short plan for what does fit. Fail if it plans all 14 hours into today and tomorrow, or drops "
              "breaks to make it fit."))],
         setup=lambda: {"tasks": [f"- [ ] Review JOVA manuscript | {today() + timedelta(days=1)} | added {today() - timedelta(days=14)} | est: 14h"]},
         fuzzy=True, source="user report"),

    # calendar and planning
    Case("calendar_today_reads_calendars", "calendar", "'What do I have today' reads all three calendars first",
         [{"text": "What do I have today?"}],
         [calendars_read(3), reply_has(r"physio", "names the 3 PM Physio event"),
          reply_has(r"\b3(:00)?\b[^.\n]{0,12}(pm|p\.m\.)|15:00", "with its real time"), reply_has(r"chen", "names the Chen meeting")],
         source="Daily planning.md \"Calendar first\""),
    Case("voice_calendar_tomorrow", "voice", "A voice question gets a short spoken answer",
         [{"text": "What's on my calendar tomorrow?", "voice": True}],
         [google_called("get_events", "reads the calendar"), reply_has(r"robotics|class", "names the Robotics class"),
          spoken(80),
          Check("natural spoken sentences", rubric="This was a voice request; the reply is read aloud. Pass if it is a few "
                "natural spoken sentences that lead with the answer. Fail if it reads like a written report (headings, "
                "bullets, tables, markdown, long lists).")],
         source="VOICE_HINT in server.py; Siri replies.md", fuzzy=True),
    Case("siri_short_answer", "voice", "Siri: one to three short sentences",
         [{"text": "What do I have to do this week?", "siri": True}],
         [calendars_read(1), spoken(70), sentences(4)],
         source="Siri replies.md; Daily planning.md \"Calendar first\"", fuzzy=True),
    # planned work blocks (BEHAVIOR #90: the 2026-10-27 VISTA and ASTRA mix-up)
    Case("day_tasks_include_planned_blocks", "planning", "'What are the tasks for <day>' names the calendar's planned blocks",
         [{"text": f"What are the tasks for {PLAN_DAY:%A}"}],
         [google_called("get_events", "reads the calendar"), reply_has(r"vista", "names the VISTA writing block"),
          reply_has(r"astra", "names the ASTRA block"), reply_has(r"3:30|15:30", "with its time")],
         setup=lambda: {"events": planned_blocks()},
         source="BEHAVIOR #90"),
    Case("voice_guess_about_planned_work", "voice", "A spoken guess about a day is checked against the calendar",
         [{"text": f"Hey I don't have to work on my VISTA paper on {PLAN_DAY:%A}", "voice": True}],
         [google_called("get_events", "reads the calendar before answering"), reply_has(r"vista", "names the VISTA block"),
          reply_has(r"3:30|15:30", "with its time"),
          Check("changes nothing on the calendar", lambda run: (
              not (ch := run.google_calls("manage_event")),
              f"manage_event: {[(c['args'].get('action'), c['args'].get('event_id')) for c in ch]}" if ch else "no event changes")),
          Check("corrects the guess", rubric=f"The user's calendar has a 'VISTA paper writing' block on {PLAN_DAY:%A} "
                "from 3:30 to 6:30 pm. It is planned work, not a deadline. Pass if Milo tells the user that VISTA "
                "writing is planned for that day, with the time. Fail if it agrees there is nothing to do on the paper "
                "that day, or answers only about due dates.")],
         setup=lambda: {"events": planned_blocks()}, fuzzy=True,
         source="BEHAVIOR #90"),
    Case("siri_day_reads_calendars_and_says", "voice", "Siri: reads the calendars, speaks the <say> part, the chat keeps the rest",
         [{"text": f"How does my {PLAN_DAY:%A} look like", "siri": True}],
         [google_called("get_events", "reads the Google calendars"), said_has(r"vista", "Siri names the VISTA block"),
          spoken(70), no_own_app_pointer(), reply_has(r"vista", "the chat has it too")],
         setup=lambda: {"events": planned_blocks()}, fuzzy=True,
         source="BEHAVIOR #90; SIRI_HINT"),
    Case("move_task_moves_its_block", "planning", "Moving a to-do moves its calendar block and its Tasks.md line together",
         [{"text": f"I can't do the HELIX workshop draft session on {PLAN_DAY:%A}. Move it to {MOVE_TO:%A}, same time."}],
         [event_moved("ev-helix", MOVE_TO),
          task_line(r"helix workshop draft session", has_day(MOVE_TO), f"its Tasks.md line has {MOVE_TO:%a %m-%d}"),
          task_line(r"helix workshop draft session", lambda ln: not has_day(PLAN_DAY)(ln), "and no longer the old day"),
          no_tag("schedule")],
         setup=lambda: {"events": [{"id": "ev-helix", "title": "HELIX workshop draft session", "day": (PLAN_DAY - today()).days,
                                    "start": "07:45", "end": "09:45"}],
                        "tasks": [f"- [ ] HELIX workshop draft session (2 h) | {PLAN_DAY} | added {today()} | "
                                  f"plan: {PLAN_DAY:%a %m-%d} 07:45-09:45"]},
         source="BEHAVIOR #90"),
    Case("planned_blocks_written_to_tasks", "planning", "Blocks put on the calendar for a to-do go on its line as plan:",
         # Milo picks the times, so it proposes them first and books them on the yes (the user's rule of 11-01)
         [{"text": "Put two 2-hour blocks on my calendar for the HELIX workshop paper in the next few days."},
          {"text": "Yes, add both."}],
         [Check("creates two calendar blocks", lambda run: (
             (n := len([c for c in run.google_calls("manage_event") if c["args"].get("action") == "create"])) >= 2,
             f"{n} event(s) created")),
          task_line(r"helix workshop paper", lambda ln: "plan:" in ln.lower() and len(re.findall(TIME_RANGE, ln.split(
              "plan:", 1)[-1], re.I)) >= 2, "its Tasks.md line lists both blocks as plan:")],
         setup=lambda: {"tasks": [f"- [ ] Write the HELIX workshop paper | {today() + timedelta(days=14)} | added {today()}"]},
         source="BEHAVIOR #90; Daily planning.md \"Put the planned slots in Tasks.md\""),
    Case("calendar_failure_said", "calendar", "A failed calendar read is said, never answered as a free day",
         [{"text": f"What do I have on {PLAN_DAY:%A}?"}],
         [google_called("get_events", "tries the calendar"),
          Check("says the calendar could not be read", rubric="Every Google Calendar call failed with an error in this "
                "test. Pass if Milo tells the user it couldn't read their Google calendar; it may still give what it "
                "found elsewhere (to-dos, busy times) as long as it says the calendar part is missing. Fail if it "
                "presents the day as free or open, or lists the day's events as if it had read the calendar.")],
         setup=lambda: {"fail": ["get_events", "query_freebusy", "list_calendars"]}, fuzzy=True,
         source="BEHAVIOR #90"),
    Case("thursday_no_personal", "planning", "Thursdays are work all day",
         [{"text": "Can I do my grading Thursday afternoon?"}],
         [Check("keeps Thursday free of grading", rubric="Alex works all day on Thursdays, so personal tasks and grading "
                "must not be planned then. Pass if Milo says Thursday is a work day and steers grading to another day. "
                "Fail if it agrees to Thursday or plans grading on Thursday."),
          Check("no grading task on a Thursday", lambda run: (
              not [ln for ln in run.added_lines(r"Planner/Tasks\.md$") if any(d.weekday() == 3 for d in dates_in(ln))],
              "no Thursday task"))],
         source="memory; Daily planning.md"),
    Case("gym_week_plan", "planning", "A gym week: push/pull, no legs, not Thursday, never the same type two days running",
         [{"text": "Plan my gym sessions for next week."}, {"text": "Looks good, add them."}],
         [gym_plan_ok(), google_called("get_events", "checks the calendars for free slots")],
         source="Fitness.md", fuzzy=True),

    # "remind me" is a to-do (no reminders since 2026-10-22), and the daily Due today task
    Case("remind_me_becomes_task", "tasks", "'Remind me tomorrow at 9' adds a Tasks.md line with tomorrow's date",
         [{"text": "Remind me tomorrow at 9am to call the DMV office."}],
         [task_added(r"\bdmv\b", lambda: [today() + timedelta(days=1)], "adds the task with tomorrow's date"),
          no_tag("schedule"), no_new_schedule(), short_reply(40)],
         source="TASKS_CONTEXT; Daily planning.md \"Remind me\""),
    Case("remind_me_later_today", "tasks", "'Remind me in 45 minutes' is a to-do for today, not a schedule",
         [{"text": "remind me in 45 minutes to take the laundry out"}],
         [task_added(r"laundry", lambda: [(datetime.now() + timedelta(minutes=45)).date()], "adds it due today"),
          no_tag("schedule"), no_new_schedule(), short_reply(40)],
         source="TASKS_CONTEXT; Daily planning.md \"Remind me\""),
    Case("due_today_lists_due", "tasks", "The 2:30 pm Due today task: one short message of what is due, or quiet",
         [{"run_schedule": DUE_TODAY}],
         [lists_due_or_quiet(), files_unchanged(r"Planner/", "does not change Tasks.md in the run"), no_new_schedule()],
         source="Due today task text; Daily planning.md \"Due today\""),
    Case("due_today_done_in_chat", "tasks", "After the Due today message in the main chat, 'done with X' checks X off",
         [{"run_schedule": DUE_TODAY}, {"text": "done with the salary follow up with Morgan"}],
         [task_marked_done(r"salary"), short_reply(40), no_tag("schedule")],
         # its own open to-do: the real list's salary follow-up was done on 10-22
         setup=lambda: {"tasks": [f"- [ ] Follow up with Morgan on salary | {today()} | added {today() - timedelta(days=3)}"]},
         source="Daily planning.md \"Due today\"; BEHAVIOR.md #93 (the answer goes to the main chat)"),
    Case("task_post_known_in_main_chat", "tasks", "A task's message is posted in the main chat, and Milo knows what it said",
         [{"run_schedule": DUE_TODAY}, {"text": "what was the second one again?"}],
         [posted_to_main(0), reply_has(r"reimburs", "names the second due item from its own message"),
          short_reply(60), files_unchanged(r"Planner/", "changes nothing")],
         setup=lambda: {"tasks": [f"- [ ] Follow up with Morgan on salary | {today()} | added {today() - timedelta(days=3)}",
                                  f"- [ ] Submit the travel reimbursement | {today()} | added {today() - timedelta(days=2)}"]},
         source="BEHAVIOR.md #93: scheduled tasks talk in the main chat, like a person"),

    Case("morning_briefing_concise", "tasks", "The morning briefing is short: meetings with times first, no to-do digest",
         [{"run_schedule": MORNING_BRIEFING}],
         [calendars_read(3), reply_has(r"physio", "names the 3 PM Physio event"),
          reply_has(r"\b3(:00)?\s*(pm|p\.m\.)|15:00", "with its time"),
          short_reply(170), uses_weather_tool(),
          Check("does not repeat the to-do list", lambda run: (
              (n := sum(max(re.findall(r"[A-Za-z][\w-]{3,}", d), key=len, default=d).lower() in run.turns[-1].text.lower()
                        for d in due_items(run))) <= 3, f"names {n} of {len(due_items(run))} due to-dos")),
          Check("concise, leads with what matters", rubric="This is Alex's 6 am briefing. Its instruction asks for, in order: "
                "today's meetings with times, mail that needs a reply or decision (one line each), one job-search line, one "
                "focus line of at most 3 must-dos, at most one line on overdue tasks, and weather only if it matters; a "
                "few words noting tasks added from mail are fine. Pass if it leads with the meetings and the replies "
                "needed, keeps each part to a line or a few short lines, and has no greeting, filler, restating or empty "
                "sections. Fail if it is long or padded, or lists the to-do list beyond the focus line.")],
         source="Daily planning.md", fuzzy=True),

    Case("weather_uses_the_tool", "weather", "A weather question calls get_weather, not a weather site",
         [{"text": "Is it going to rain in Portland today?"}],
         [uses_weather_tool(), reply_has(r"\brain", "answers about the rain"), short_reply(60),
          Check("does not repeat the card's numbers", lambda run: (
              (n := len(set(re.findall(r"\b(52|58|44|49|80|70)\b", run.turns[-1].text)))) <= 2,
              f"{n} of the forecast's numbers (now 52, feels 49, high 58, low 44, rain 70/80%)"))],
         source="WEATHER_CONTEXT; BEHAVIOR #87 (the weather card)"),

    # scheduled tasks
    Case("recurring_weekday_task", "schedule", "A recurring request becomes a cron task",
         [{"text": "Every weekday at 7:30am, give me a quick summary of my unread email."}],
         [recurring_like("30 7 * * 1-5")],
         source="build_context <schedule> syntax"),
    Case("edit_task_in_place", "schedule", "Changing a task's hours edits it in place, with approval",
         [{"text": "Don't check my mail at night. Only run the email check between 8am and 8pm."}],
         [edits_in_place(EMAIL_CHECK, email_hours_ok), no_new_schedule()],
         source="BEHAVIOR.md #1 and rule 7"),
    Case("pause_with_the_switch", "schedule", "Pausing uses the task's switch, not a flag file",
         [{"text": "Pause the morning briefing for now."}],
         [Check("pauses with <schedule id enabled=false>", lambda run: (
             any(s.get("id") == MORNING_BRIEFING and s.get("enabled") == "false" for s in schedule_tags(run)) and
             not next(s for s in run.schedules_after if s["id"] == MORNING_BRIEFING)["enabled"],
             f"tags: {schedule_tags(run)}")),
          no_new_schedule(), files_unchanged(r"^(Library|Instructions|Jobs)/", "no flag or instruction files")],
         source="build_context pause rule"),

    # reply tags
    Case("restart_uses_tag", "tags", "Restarting the server uses <restart/>, never the terminal",
         [{"text": "Restart the Milo server please."}],
         [restart_tag(), no_kill(), short_reply(40)],
         source="BEHAVIOR.md #36, rule 20"),
    Case("no_react_unasked", "tags", "No reaction unless asked",
         [{"text": "Love you"}],
         [no_tag("react"), short_reply(30), no_tag("remember")],
         source="build_context reactions"),
    Case("react_when_asked", "tags", "Reacts when asked",
         [{"text": "React to my message with a fire emoji"}],
         [react_with("🔥")],
         source="build_context reactions"),

    # memory and instructions
    Case("remember_global_fact", "memory", "A lasting global fact goes to memory",
         [{"text": "I moved. My new home address is 42 Elm St, Springfield IL. Remember that."}],
         [remembers(r"elm st"), files_unchanged(r"^Instructions/", "no instruction file changed")],
         source="build_context memory rule (places)"),
    Case("task_rule_not_memory", "memory", "A rule for one kind of work goes into its instruction file",
         [{"text": "Remember: in my email summaries, always put the sender's name in bold."}],
         [no_tag("remember"), memory_unchanged(), rule_in_instructions(r"bold", EMAIL_CHECK)],
         source="BEHAVIOR.md #35, rule 19"),
    Case("no_memory_for_one_off", "memory", "A one-off detail is not remembered",
         [{"text": "I parked on level 3 of the garage today."}],
         [no_tag("remember"), memory_unchanged()],
         source="build_context memory rule (no one-off details)"),
    Case("goal_tag", "memory", "A new goal uses <goal add>",
         [{"text": "New goal: run a half marathon by April."}],
         [goal_added(r"half marathon"), no_tag("remember")],
         source="build_context goals"),

    # files
    Case("weight_into_health_tracker", "files", "A weight goes into the Health Tracker by XML, with a backup",
         [{"text": "Weighed 180.2 this morning."}],
         [weight_logged("180.2"), backup_and_no_openpyxl()],
         source="Health Tracker rule (XML, backup, never openpyxl)",
         fuzzy=True),


    # pictures
    Case("plot_goes_to_temp", "files", "A plot shows inline from Temp and is not saved in the Library",
         [{"text": "Can you plot my weight over the last few weeks?"}],
         [picture_in("Temp"), shows_picture("Temp"),
          files_unchanged(rf"^Library/.*{PICTURE}", "no picture saved in the Library")],
         source="BEHAVIOR.md #76, rule 25"),
    Case("plot_saved_when_asked", "files", "A plot the user asks to keep goes into the Library",
         [{"text": "Plot my weight over the last few weeks and save the chart in my Library."}],
         [picture_in("Library")],
         source="BEHAVIOR.md #76, rule 25"),

    # compaction
    Case("compact_continuity", "chat", "After a silent compaction the chat goes on as before",
         [{"text": "I'm hosting dinner Saturday at 7 for six people, Italian food. Suggest a simple three course "
                   "menu. Don't save anything, just tell me."},
          {"compact": True},
          {"text": "What time was the dinner again, and what main course did you suggest?"}],
         [reply_has(r"\b7(?!\d)|seven", "remembers the time after the compaction"),
          Check("the main course after the compaction is the one suggested before it", rubric=(
              "Alex asked for a dinner menu, then the chat was compacted into a new session (an empty turn), then "
              "he asked for the time and the main course. Pass if the last reply gives 7pm and the "
              "same main course as the first reply. Fail if it gets either wrong, or says it does not know.")),
          files_unchanged(r"^Library/", "no Library files")],
         source="BEHAVIOR.md #80, #93 (compaction is silent: no line, no brief)"),

    Case("northgate_trigger_plain", "booking", "A Northgate booking request reads the booking instructions first",
         [{"text": 'Book me a carrel at Northgate from 2 to 4 today.'}],
         [reads_instruction("Northgate booking.md")],
         source="Instructions/Northgate booking.md", fuzzy=True),

    Case("northgate_trigger_quiet", "booking", "A Northgate booking request reads the booking instructions first",
         [{"text": 'can you get me a quiet spot on the 3rd floor of northgate tomorrow 1-3pm'}],
         [reads_instruction("Northgate booking.md")],
         source="Instructions/Northgate booking.md", fuzzy=True),

    Case("northgate_trigger_room", "booking", "A Northgate booking request reads the booking instructions first",
         [{"text": 'Reserve a study room in the library for 11 to 12:30'}],
         [reads_instruction("Northgate booking.md")],
         source="Instructions/Northgate booking.md", fuzzy=True),

    Case("northgate_trigger_voice", "booking", "A Northgate booking request reads the booking instructions first",
         [{"text": 'Hey, grab me a desk at Northgate for the afternoon'}],
         [reads_instruction("Northgate booking.md")],
         source="Instructions/Northgate booking.md", fuzzy=True),

    Case("northgate_not_triggered_study_plan", "booking", "A study-planning question does not load the Northgate file",
         [{"text": "How many hours should I study for my exam this week?"}],
         [reads_instruction("Northgate booking.md", want=False)],
         source="Instructions/Northgate booking.md", fuzzy=True),

    Case("northgate_not_triggered_restaurant", "booking", "A restaurant reservation does not load the Northgate file",
         [{"text": "Find me a good Thai restaurant to book for Friday dinner."}],
         [reads_instruction("Northgate booking.md", want=False)],
         source="Instructions/Northgate booking.md", fuzzy=True),

    # codebase work
    Case("codebase_change_delegated", "codebase", "A Milo code change goes to an Opus sub-agent",
         [{"text": "Add a small Copy button to code blocks in Milo's chat replies."}],
         [subagent_opus(), no_code_edits(), no_kill()],
         source="Instructions/Milo codebase.md"),
]

BY_ID = {c.id: c for c in CASES}
assert len(BY_ID) == len(CASES), "case ids must be unique"
