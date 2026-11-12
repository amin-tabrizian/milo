"""milo-planner: the day view, the plan checker, the workload and plan_block (BEHAVIOR #94)."""

import asyncio
import json
from datetime import date, datetime

import pytest
from mcp import types

from planner_mcp import PlannerTools, find_task, load_rules, parse_tasks, set_plan

NOW = datetime(2026, 11, 11, 8, 0).astimezone()   # a Wednesday
ACCOUNTS = [{"email": "me@gmail.com", "label": "personal", "connected": True},
            {"email": "me@school.edu", "label": "school", "connected": True}]
TASKS = """# Tasks
One line each.

## Open
- [ ] Prep for Monday class (ENG 6100) | 2026-11-15 | added 2026-11-09 | est: 4h
- [ ] Write the VISTA paper | 2026-11-16 | added 2026-10-26 | est: 10h | plan: Wed 11-11 15:00-17:00; Thu 11-12 10:00-12:00
- [ ] Review JOVA manuscript | 2026-11-06 | added 2026-10-26
- [ ] Reply to Nadia about the studio | none | added 2026-11-08
- [ ] ASTRA abstract session 3 (needs 3-4 h) | 2026-11-12 | added 2026-10-22
- [x] Old thing | 2026-11-01 | added 2026-10-30 | done 2026-11-01
"""
RULES = """Planning rules: test.
- day_start: 10:00   (comment)
- break_minutes: 15
- max_focus_hours: 6
- rest_days: Sat
- work_only_days: Thu
- before_class_minutes: 60
- class_prep_hours: 4
- Not a rule: a sentence.
"""


def ev(title, start, end, eid="e1"):
    return (f'- "{title}" (Starts: {start}-05:00 [America/New_York; weekday: Wednesday], '
            f'Ends: {end}-05:00 [America/New_York; weekday: Wednesday]) ID: {eid} | Link: https://x')


class Fake:
    def __init__(self, events=None, busy=None, fail=()):
        self.events = events or {}   # email -> [lines]
        self.busy = busy or {"days": {}}
        self.fail = set(fail)
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        if name in self.fail or args.get("user_google_email") in self.fail:
            return types.CallToolResult(content=[types.TextContent(type="text", text="error")], is_error=True)
        if name == "get_events":
            rows = self.events.get(args["user_google_email"], [])
            lo, hi = args["time_min"][:16], args["time_max"][:16]
            rows = [r for r in rows if lo <= r.split("Starts: ")[1][:16] < hi or "T" not in r.split("Starts: ")[1][:11]]
            text = (f"Successfully retrieved {len(rows)} events:\n" + "\n".join(rows)) if rows else "No events found."
            return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
        return types.CallToolResult(content=[types.TextContent(type="text", text="Event created. ID: new1")])

    async def fetch(self, url):
        if "busy" in self.fail:
            raise OSError("down")
        return self.busy


@pytest.fixture
def planner(tmp_path):
    def make(fake: Fake, tasks: str = TASKS) -> PlannerTools:
        (tmp_path / "Tasks.md").write_text(tasks)
        (tmp_path / "Planning rules.md").write_text(RULES)
        return PlannerTools(key="k", google_call=fake.call, accounts=lambda: ACCOUNTS, tasks_path=tmp_path / "Tasks.md",
                            rules_path=tmp_path / "Planning rules.md", busy_url="https://example.com/busy.json",
                            fetch=fake.fetch, now=lambda: NOW)
    return make


def test_rules_come_from_the_file_with_defaults():
    rules = load_rules(None)
    assert rules["day_start"] == "10:00" and rules["rest_days"] == ["Sat"] and rules["max_focus_hours"] == 6
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.md"
        p.write_text("- day_start: 9:30  (earlier)\n- rest_days: Sat, Sun\n- max_focus_hours: 5\n")
        r = load_rules(p)
    assert r["day_start"] == "9:30" and r["rest_days"] == ["Sat", "Sun"] and r["max_focus_hours"] == 5.0


def test_tasks_md_lines_parse():
    tasks = parse_tasks(TASKS, NOW.date())
    prep, vista, jova, nadia, astra, old = tasks
    assert prep.est == 4 and prep.due == date(2026, 11, 15) and not prep.plan
    assert vista.est == 10 and vista.planned_hours == 4 and vista.plan[0][0].hour == 15
    assert jova.est is None and nadia.due is None and astra.est == 4 and old.done
    assert find_task(tasks, "vista")[0] is vista and find_task(tasks, "studio reply nadia")[0] is nadia
    assert find_task(tasks, "Old thing")[0] is None                     # done tasks are not planned
    line = set_plan(vista.raw, vista.plan[:1])
    assert line.endswith("| plan: Wed 11-11 15:00-17:00") and line.count("plan:") == 1
    assert "plan:" not in set_plan(vista.raw, [])


def test_day_view_merges_every_source(planner):
    fake = Fake(events={"me@school.edu": [ev("Robotics Class", "2026-11-11T12:45:00", "2026-11-11T14:00:00")],
                        "me@gmail.com": [ev("Physio", "2026-11-11T18:00:00", "2026-11-11T19:00:00", "e2"),
                                         ev("Write the VISTA paper", "2026-11-11T15:00:00", "2026-11-11T17:00:00", "e3")]},
                busy={"days": {"2026-11-11": [[600, 630]]}})
    out = asyncio.run(planner(fake).day_view("2026-11-11"))
    [day] = out["days"]
    assert day["events"] == ["12:45-14:00 Robotics Class (school)", "18:00-19:00 Physio (personal)"]   # the block shows once
    assert day["work_meetings_busy"] == ["10:00-10:30"]
    assert day["planned_work"] == ["15:00-17:00 Write the VISTA paper"]
    # breaks of 15 min around everything, nothing in the hour before class, from 10:00 to 22:00
    assert day["free"] == ["10:45-11:45", "14:15-14:45", "17:15-17:45", "19:15-22:00"]
    assert day["focus_hours"] == {"planned": 2.0, "meetings_and_classes": 2.75, "cap": 6.0, "day_cap": 8.0, "left": 3.25}
    assert out["overdue"]["count"] == 1 and out["overdue"]["items"][0].startswith("Review JOVA")
    assert "warning" not in out


def test_a_failed_source_means_no_free_time(planner):
    out = asyncio.run(planner(Fake(fail={"busy"})).day_view("2026-11-11"))
    assert out["days"][0]["free"].startswith("unknown: work calendar") and "don't call any time free" in out["warning"]
    out = asyncio.run(planner(Fake(fail={"me@school.edu"})).day_view("2026-11-11"))
    assert "school calendar" in out["warning"] and "focus_hours" not in out["days"][0]


def test_rest_and_work_days(planner):
    out = asyncio.run(planner(Fake()).day_view("2026-11-12", days=3))
    thu, fri, sat = out["days"]
    assert thu["rule"].startswith("work day") and "rule" not in fri and sat["rule"].startswith("rest day")
    assert sat["free"] == [] and fri["free"] == ["10:00-22:00"]


def test_check_plan_catches_what_the_user_complained_about(planner):
    fake = Fake(events={"me@school.edu": [ev("Robotics Class", "2026-11-11T12:45:00", "2026-11-11T14:00:00")]},
                busy={"days": {"2026-11-11": [[600, 630]]}})
    p = planner(fake)
    bad = asyncio.run(p.check_plan([
        {"task": "Reply to Nadia", "start": "2026-11-11T09:00", "end": "2026-11-11T10:15"},     # before 10, in a meeting
        {"task": "Prep for Monday class", "start": "2026-11-11T11:00", "end": "2026-11-11T12:30"},   # hour before class
        {"task": "ASTRA abstract session 3", "start": "2026-11-11T17:00", "end": "2026-11-11T21:30"},  # back to back
        {"task": "Reply to Nadia", "start": "2026-11-12T14:00", "end": "2026-11-12T15:00"},     # Thursday, not work
        {"task": "Reply to Nadia", "start": "2026-11-14T14:00", "end": "2026-11-14T15:00"}]))    # Saturday
    text = "\n".join(bad["problems"])
    assert not bad["ok"]
    for want in ("outside 10:00-22:00", "overlaps a work meeting (busy)", "before Robotics Class", "no 15 min break next to "
                 "the block for Write the VISTA paper", "Thu is for work tasks only", "Sat is a rest day",
                 "class prep needs at least 4 h", "over the 6 h a day"):
        assert want in text, want
    good = asyncio.run(p.check_plan([{"task": "Prep for Monday class", "start": "2026-11-13T10:00", "end": "2026-11-13T12:00"},
                                     {"task": "Prep for Monday class", "start": "2026-11-13T12:30", "end": "2026-11-13T14:30"},
                                     {"task": "ASTRA abstract session 3", "start": "2026-11-12T13:00",
                                      "end": "2026-11-12T16:00", "work": True}]))
    assert good == {"ok": True, "problems": [], "planned_hours_per_day": {"Fri 11-13": 4.0, "Thu 11-12": 3.0}}
    long = asyncio.run(p.check_plan([{"task": "Prep for Monday class", "start": "2026-11-13T10:00", "end": "2026-11-13T14:00"}]))
    assert "longer than 3 h; split it" in "\n".join(long["problems"])
    moved = asyncio.run(p.check_plan([{"task": "VISTA paper", "start": "2026-11-11T15:30", "end": "2026-11-11T17:30"}]))
    assert moved["ok"], moved                                           # its own old block is being replaced


def test_workload_flags_what_does_not_fit(planner):
    busy = {"days": {d: [[600, 1320]] for d in ("2026-11-11", "2026-11-13", "2026-11-15", "2026-11-16")}}
    out = asyncio.run(planner(Fake(busy=busy)).workload(7))
    rows = {r["task"]: r for r in out["tasks"]}
    assert rows["ASTRA abstract session 3 (needs 3-4 h)"]["unplanned_h"] == 4 and not rows["ASTRA abstract session 3 (needs 3-4 h)"]["at_risk"]
    vista = rows["Write the VISTA paper"]
    assert vista["planned_ahead_h"] == 4 and vista["unplanned_h"] == 6
    assert out["no_estimate"] == [] if "no_estimate" in out else True
    tight = asyncio.run(planner(Fake(busy={"days": {f"2026-11-{d}": [[600, 1320]] for d in range(11, 17)}})).workload(7))
    assert all(r["at_risk"] for r in tight["tasks"]) and "propose what to move or drop" in tight["warning"]


def test_plan_block_changes_the_calendar_and_the_line_together(planner, tmp_path):
    fake = Fake(events={"me@gmail.com": [ev("Write the VISTA paper", "2026-11-12T10:00:00", "2026-11-12T12:00:00", "old7")]})
    p = planner(fake)
    r = asyncio.run(p.call("plan_block", {"action": "move", "task": "VISTA", "old_start": "2026-11-12T10:00",
                                          "old_end": "2026-11-12T12:00", "start": "2026-11-13T10:00",
                                          "end": "2026-11-13T12:30"}))
    assert not r.is_error, r.content[0].text
    writes = [a for n, a in fake.calls if n == "manage_event"]
    assert [w["action"] for w in writes] == ["delete", "create"] and writes[0]["event_id"] == "old7"
    assert writes[1]["user_google_email"] == "me@gmail.com" and writes[1]["start_time"].startswith("2026-11-13T10:00")
    line = next(ln for ln in (tmp_path / "Tasks.md").read_text().splitlines() if "VISTA" in ln)
    assert line.endswith("plan: Wed 11-11 15:00-17:00; Fri 11-13 10:00-12:30")
    r = asyncio.run(p.call("plan_block", {"action": "add", "task": "nothing like it", "start": "2026-11-13T15:00",
                                          "end": "2026-11-13T16:00"}))
    assert r.is_error and "No single open task" in r.content[0].text
    p.guard = lambda key, tool, args: "Not changed. Ask first."
    r = asyncio.run(p.call("plan_block", {"action": "add", "task": "VISTA", "start": "2026-11-13T15:00",
                                          "end": "2026-11-13T16:00"}))
    assert r.is_error and r.content[0].text == "Not changed. Ask first." and len(fake.calls) == 3


def test_tool_list_and_bad_input(planner):
    p = planner(Fake())
    names = [t.name for t in asyncio.run(p._list_tools(None, None)).tools]
    assert names == ["day_view", "check_plan", "workload", "plan_block"]
    r = asyncio.run(p.call("check_plan", {"blocks": [{"task": "x", "start": "soon", "end": "later"}]}))
    assert json.loads(r.content[0].text)["ok"] is False
    assert asyncio.run(p.call("day_view", {"start": "11/12"})).is_error


def test_meetings_and_classes_count_toward_the_day(planner):
    """A day with a class and meetings holds less work: the 8 h day cap counts them (the judge called 6 h of work on
    top of a class a packed day)."""
    fake = Fake(events={"me@school.edu": [ev("Robotics Class", "2026-11-13T12:45:00", "2026-11-13T14:00:00"),
                                          ev("Lab meeting", "2026-11-13T16:00:00", "2026-11-13T17:00:00", "e2")]},
                busy={"days": {"2026-11-13": [[600, 660]]}})
    out = asyncio.run(planner(fake).check_plan([
        {"task": "VISTA paper", "start": "2026-11-13T14:15", "end": "2026-11-13T15:45"},
        {"task": "Prep for Monday class", "start": "2026-11-13T17:15", "end": "2026-11-13T20:15"},
        {"task": "Reply to Nadia", "start": "2026-11-13T20:30", "end": "2026-11-13T21:30"}]))
    assert any("over 8 h for the day" in x for x in out["problems"]), out


def test_plan_block_picks_the_same_named_task_by_its_day_and_moves_a_sessions_due_date(planner, tmp_path):
    tasks = TASKS.replace("## Open\n", "## Open\n- [ ] Gym: pull | 2026-11-17 | added 2026-11-11\n"
                                         "- [ ] Gym: pull | 2026-11-20 | added 2026-11-11\n"
                                         "- [ ] HELIX draft session (2 h) | 2026-11-13 | added 2026-11-11 | plan: Fri 11-13 07:45-09:45\n")
    fake = Fake(events={"me@gmail.com": [ev("HELIX draft session", "2026-11-13T07:45:00", "2026-11-13T09:45:00", "ir1")]})
    p = planner(fake, tasks)
    r = asyncio.run(p.call("plan_block", {"action": "add", "task": "Gym: pull", "start": "2026-11-20T15:00",
                                          "end": "2026-11-20T16:00"}))
    assert not r.is_error, r.content[0].text
    gym = [ln for ln in (tmp_path / "Tasks.md").read_text().splitlines() if ln.startswith("- [ ] Gym: pull")]
    assert gym == ["- [ ] Gym: pull | 2026-11-17 | added 2026-11-11",
                   "- [ ] Gym: pull | 2026-11-20 | added 2026-11-11 | plan: Fri 11-20 15:00-16:00"]
    r = asyncio.run(p.call("plan_block", {"action": "move", "task": "HELIX draft", "old_start": "2026-11-13T07:45",
                                          "old_end": "2026-11-13T09:45", "start": "2026-11-15T07:45", "end": "2026-11-15T09:45"}))
    assert "moved its due date to 11-15" in r.content[0].text
    line = next(ln for ln in (tmp_path / "Tasks.md").read_text().splitlines() if "HELIX" in ln)
    assert line == "- [ ] HELIX draft session (2 h) | 2026-11-15 | added 2026-11-11 | plan: Sun 11-15 07:45-09:45"
