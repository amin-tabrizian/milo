"""Memory, directives, scheduler, activity, library and the context block."""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from features import Activity, Library, Memory, Scheduler, build_context, extract_directives
from speech import speakable


# directives


def test_remember_tags_are_extracted_and_stripped():
    text, facts, schedules = extract_directives("Got it.<remember>Prefers short answers</remember> Done.")
    assert text == "Got it. Done."
    assert facts == ["Prefers short answers"]
    assert schedules == []


def test_schedule_tags_parse_when_and_cron():
    reply = ('OK.\n<schedule when="2030-01-02T09:00" kind="task" title="Slides">Make the slides</schedule>\n'
             '<schedule cron="0 8 * * 1-5" kind="task" title="Brief">Brief me</schedule>')
    text, facts, schedules = extract_directives(reply)
    assert text == "OK."
    assert schedules[0] == {"when": "2030-01-02T09:00", "cron": None, "title": "Slides", "text": "Make the slides"}
    assert schedules[1]["cron"] == "0 8 * * 1-5"


def test_schedule_tags_with_an_id_pause_or_resume():
    text, _, schedules = extract_directives('Paused.<schedule id="abc" enabled="false"></schedule>'
                                            '<schedule id="def" enabled="true"></schedule>')
    assert text == "Paused." and schedules == [{"id": "abc", "enabled": False}, {"id": "def", "enabled": True}]


def test_schedule_tags_with_an_id_change_a_task():
    _, _, schedules = extract_directives('Asked.<schedule id="abc" cron="0 * * * *" title="Sweep">Run it</schedule>')
    assert schedules == [{"id": "abc", "cron": "0 * * * *", "title": "Sweep", "text": "Run it"}]   # no switch change


@pytest.mark.parametrize("when, cron, label", [
    (None, "*/30 * * * *", "Every 30 minutes"), (None, "0 * * * *", "Every hour"), (None, "15 */2 * * *", "Every 2 hours at :15"),
    (None, "0 8 * * 1-5", "Weekdays at 8:00 AM"), (None, "30 18 * * *", "Every day at 6:30 PM"),
    (None, "0 9 * * 1", "Every Monday at 9:00 AM"), (None, "0 9 1 * *", "Custom (0 9 1 * *)"),
    ("2030-01-02T09:00", None, "Once, Jan 2 at 9:00 AM")])
def test_when_label(when, cron, label):
    from features import when_label
    assert when_label(when, cron) == label


def test_text_without_tags_is_unchanged():
    assert extract_directives("Plain reply.") == ("Plain reply.", [], [])


def test_usage_text_becomes_limits_and_notes():
    from zoneinfo import ZoneInfo
    from features import parse_usage
    now = datetime(2026, 12, 30, 22, 0, tzinfo=ZoneInfo("America/New_York"))
    text = ("You are currently using your subscription to power your Claude Code usage\n\n"
            "Current session: 55% used · resets 3:09am (America/New_York)\n"
            "Current week (all models): 44% used · resets Jan 2 at 3am (America/New_York)\n"
            "Current week (Sonnet only): 3% used\n\n"
            "What's contributing to your limits usage?\n\n"
            "Last 24h · 613 requests · 22 sessions\n  70% of your usage was at >150k context\n\n"
            "Last 7d · 700 requests · 25 sessions\n  Top MCP servers: milo-browser 44%\n")
    u = parse_usage(text, now)
    assert [(l["label"], l["used"], l["resets"]) for l in u["limits"]] == [
        ("This session", 55, "2026-12-31T03:09:00-05:00"),       # a time only: the next one
        ("This week (all models)", 44, "2027-01-02T03:00:00-05:00"),   # next year
        ("This week (Sonnet only)", 3, None)]
    assert u["notes"] == [{"title": "Last 24h · 613 requests · 22 sessions", "lines": ["70% of your usage was at >150k context"]},
                          {"title": "Last 7d · 700 requests · 25 sessions", "lines": ["Top MCP servers: milo-browser 44%"]}]
    assert parse_usage("no limits here") == {"limits": [], "notes": []}


# memory


def test_memory_add_deduplicates(tmp_path):
    m = Memory(tmp_path / "memory.md")
    m.add("Likes tea")
    m.add("Likes   tea")
    m.add("Lives in Denver")
    assert m.read().splitlines() == ["- Likes tea", "- Lives in Denver"]


def test_memory_version_changes_on_write(tmp_path):
    m = Memory(tmp_path / "memory.md")
    before = m.version
    time.sleep(0.01)
    m.write("- new")
    assert m.version != before


# scheduler


async def _noop(item):
    pass


def test_scheduler_one_time_and_cron(tmp_path):
    s = Scheduler(tmp_path / "s.json", _noop)
    when = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
    one = s.add(title="t", text="x", when=when.isoformat())
    assert abs(one["next"] - when.timestamp()) < 1
    cron = s.add(title="c", text="y", cron="0 8 * * 1-5")
    assert cron["next"] > time.time()
    assert [i["id"] for i in s.upcoming()][0] == min((one, cron), key=lambda i: i["next"])["id"]


@pytest.mark.parametrize("kwargs", [{"cron": "not a cron"}, {}])
def test_scheduler_rejects_bad_input(tmp_path, kwargs):
    s = Scheduler(tmp_path / "s.json", _noop)
    with pytest.raises(ValueError):
        s.add(title="t", text="x", **kwargs)


def test_scheduler_toggle_and_remove(tmp_path):
    s = Scheduler(tmp_path / "s.json", _noop)
    item = s.add(title="t", text="x", cron="*/5 * * * *")
    assert s.toggle(item["id"], False)["enabled"] is False
    assert s.remove(item["id"]) is True
    assert s.remove(item["id"]) is False


def test_scheduler_edit_keeps_the_task(tmp_path):
    s = Scheduler(tmp_path / "s.json", _noop)
    item = s.add(title="Sweep", text="x", cron="*/30 * * * *")
    s.toggle(item["id"], False)
    s.set_auto_approve(item["id"], True)
    s.log_run(item["id"], "done", "c1", "run 1")
    with pytest.raises(ValueError):
        s.edit(item["id"], cron="every hour")
    assert s.get(item["id"])["cron"] == "*/30 * * * *"                       # a bad change changes nothing
    edited = s.edit(item["id"], cron="0 * * * *", text="y")
    assert edited["id"] == item["id"] and edited["cron"] == "0 * * * *" and edited["text"] == "y"
    assert edited["title"] == "Sweep" and edited["enabled"] is False and edited["auto_approve"] is True
    assert len(s.store.data) == 1 and s.history_of(item["id"])[0]["summary"] == "run 1"
    assert s.edit("nope", title="t") is None


def test_task_history_keeps_recent_runs(tmp_path, monkeypatch):
    import features
    monkeypatch.setattr(features, "HISTORY_LIMIT", 3)
    s = Scheduler(tmp_path / "s.json", _noop)
    item = s.add(title="t", text="x", cron="*/5 * * * *")
    ids = [s.log_run(item["id"], "done", "c1", f"run {i}") for i in range(4)]
    s.update_run(ids[-1], "running")
    assert [r["summary"] for r in s.history_of(item["id"])] == ["run 3", "run 2", "run 1"]   # newest first
    assert Scheduler(tmp_path / "s.json", _noop).history_of(item["id"])[0]["status"] == "interrupted"   # restarted
    s.remove(item["id"])
    assert s.history_of(item["id"]) == []


def test_scheduler_context_lists_items_and_tracks_changes(tmp_path):
    s = Scheduler(tmp_path / "s.json", _noop)
    assert s.context() == ""
    v = s.version
    item = s.add(title="Wake up", text="Time to get up", cron="0 6 * * *")
    assert s.version > v and s.context() == f"- [{item['id']}] (cron 0 6 * * *) Wake up: Time to get up"
    v = s.version
    s.toggle(item["id"], False)
    assert s.version > v and "paused) Wake up" in s.context()
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    ctx = build_context(settings, "", Path("/tmp/lib"), schedules=s.context())
    assert "paused) Wake up" in ctx and "live state of the Upcoming tab" in ctx and "Be concise" in ctx


def test_context_turns_remind_me_into_a_task(tmp_path):
    """No reminders: "remind me to X on Y" goes to Tasks.md with its date. The prompt shows only the task form."""
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    (tmp_path / "Planner").mkdir()
    (tmp_path / "Planner" / "Tasks.md").write_text("# Tasks\n")
    ctx = build_context(settings, "", tmp_path)
    assert 'Remind me to X (on/at Y)" is a to-do too' in ctx and "do not make a <schedule> for it" in ctx
    assert ctx.lower().count("reminder") == 1                         # only "There are no separate reminders"
    assert '<schedule cron="0 8 * * 1-5" kind="task"' in ctx and "<quiet/>" in ctx


def test_scheduler_makes_only_tasks(tmp_path):
    s = Scheduler(tmp_path / "s.json", _noop)
    assert s.add(title="t", text="x", cron="0 9 * * *")["kind"] == "task"


def test_scheduler_drops_old_reminders_on_load(tmp_path):
    """Reminders were removed (to-dos live in Tasks.md). Old ones left in the store are dropped on start, never fired,
    and their run history goes with them; the tasks around them are kept."""
    task = {"id": "t1", "title": "Brief", "text": "Brief me", "kind": "task", "when": None, "cron": "0 6 * * *",
            "next": 0, "enabled": True}
    old = [{"id": "r1", "title": "Morning weight", "text": "Weight?", "kind": "reminder", "when": None,
            "cron": "0 6 * * *", "next": 0, "enabled": True},
           {"id": "r2", "title": "Dentist", "text": "Call", "kind": "reminder", "when": "2020-01-01T09:00", "cron": None,
            "next": 1.0, "enabled": True}]
    (tmp_path / "s.json").write_text(json.dumps([old[0], task, old[1]]))
    (tmp_path / "task_history.json").write_text(json.dumps({"r1": [{"id": "x", "ts": 1, "status": "sent"}], "t1": []}))
    fired = []

    async def fire(item):
        fired.append(item["id"])
    s = Scheduler(tmp_path / "s.json", fire)
    assert [i["id"] for i in s.store.data] == ["t1"] and "Morning weight" not in s.context()
    assert [i["id"] for i in json.loads((tmp_path / "s.json").read_text())] == ["t1"]
    assert "r1" not in s.history.data and "t1" in s.history.data
    s.store.data[0]["next"] = 1.0                                     # due now

    async def one_tick():
        s.start()
        await asyncio.sleep(0.05)
        s._task.cancel()
    asyncio.run(one_tick())
    assert fired == ["t1"]


# activity


def test_activity_upserts_by_key_and_trims(tmp_path):
    a = Activity(tmp_path / "a.json", limit=3)
    a.record("tool", "Terminal", "c1", "pending", key="k1")
    a.record("tool", "Terminal", "c1", "completed", "ls", key="k1")
    assert len(a.recent()) == 1 and a.recent()[0]["status"] == "completed"
    for i in range(5):
        a.record("tool", f"t{i}")
    assert len(a.recent()) == 3
    assert Activity(tmp_path / "a.json").recent()[0]["title"] == "t4"   # persisted


# library


def test_library_lists_and_blocks_path_traversal(tmp_path):
    lib = Library(tmp_path / "lib")
    (tmp_path / "lib" / "a.md").write_text("hi")
    (tmp_path / "secret.txt").write_text("no")
    assert [f["name"] for f in lib.list()] == ["a.md"]
    assert lib.resolve("a.md").name == "a.md"
    for bad in ("../secret.txt", "/etc/passwd", "nope.md"):
        with pytest.raises(FileNotFoundError):
            lib.resolve(bad)


def test_library_today_sorts_by_creation(tmp_path):
    """Today: files added or changed since midnight, newest added first, also when an old file changed last."""
    lib, now = Library(tmp_path / "lib"), time.time()
    for name in ("old.md", "edited.md", "first.md", "second.md"):
        (tmp_path / "lib" / name).write_text("x")
    for name, at in (("old.md", now - 3 * 86400), ("edited.md", now - 3 * 86400), ("first.md", now - 60)):
        os.utime(tmp_path / "lib" / name, (at, at))   # macOS: an older mtime moves the birth time back too
    os.utime(tmp_path / "lib" / "edited.md", (now, now))   # changed today; the birth time stays
    assert [f["name"] for f in lib.today(now - 3600)] == ["second.md", "first.md", "edited.md"]
    assert lib.today(now + 60) == []


# context block


def test_context_mentions_browser_only_when_ready():
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    without = build_context(settings, "- likes tea", Path("/tmp/lib"))
    with_browser = build_context(settings, "- likes tea", Path("/tmp/lib"), browser=True)
    assert "You are Milo" in without and "- likes tea" in without
    assert "browser_fill_credential" not in without
    assert "browser_fill_credential" in with_browser and "browser_request_takeover" in with_browser


def test_context_sends_plots_to_temp_not_the_library():
    """#76: a plot the user asks for is shown inline from Temp; it goes to the Library only when they ask to keep it."""
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    ctx = build_context(settings, "", Path("/x/Milo/Library"))
    assert '"/x/Milo/Temp", not in the Library' in ctx and "![Short title](<full path of the file>)" in ctx
    assert "only when the user asks to save or keep it" in ctx
    assert '"/t/Plots"' in build_context(settings, "", Path("/x/Milo/Library"), temp=Path("/t/Plots"))


def test_context_sends_screenshots_for_the_user_to_temp():
    """#85: a screenshot for the user is saved where the browser may write and the app serves, and shown inline."""
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    ctx = build_context(settings, "", Path("/x/Milo/Library"), browser=True, temp=Path("/t/Temp"))
    assert 'asks for a screenshot, take it with a filename in "/t/Temp"' in ctx
    assert "screenshot" not in build_context(settings, "", Path("/x/Milo/Library"), temp=Path("/t/Temp"))


def test_context_sends_weather_to_the_weather_tool():
    """#87: weather comes from get_weather (the app shows it as a card), not a weather site."""
    ctx = build_context({"assistant_name": "Milo", "tone": "warm", "length": "short"}, "", Path("/tmp/lib"))
    assert "call get_weather (milo-weather)" in ctx and "Don't search or fetch a weather site" in ctx
    assert "don't list the numbers" in ctx


def test_context_lists_task_instruction_files(tmp_path):
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    (tmp_path / "Job applications.md").write_text("\nJob applications, in chat or in the sweep.\n\n- Use the Gmail.\n")
    (tmp_path / "notes.txt").write_text("not an instruction file")
    ctx = build_context(settings, "", Path("/tmp/lib"), instructions=tmp_path)
    assert "- Job applications.md: Job applications, in chat or in the sweep." in ctx
    assert "Use the Gmail" not in ctx and "notes.txt" not in ctx   # only the index goes in every chat
    assert f"{tmp_path}/<Topic>.md" in ctx
    assert "(none yet)" in build_context(settings, "", Path("/tmp/lib"), instructions=tmp_path / "missing")


# speech


def test_speakable_removes_markup_and_code():
    out = speakable("# Title\n**Bold** and `code`.\n```py\nprint(1)\n```\nSee [docs](https://x.y).")
    assert "#" not in out and "*" not in out and "print(1)" not in out
    assert "(code omitted)" in out and "docs" in out and "https" not in out


def test_speakable_truncates_long_text_on_a_sentence():
    out = speakable("This is a sentence. " * 100, limit=120)
    assert out.endswith("The rest is on screen.") and len(out) < 200


def test_split_speech_starts_short_and_keeps_sentences():
    from speech import split_speech
    text = " ".join(f"This is sentence number {i}, which has a few words in it." for i in range(12))
    parts = split_speech(text)
    assert " ".join(parts) == text
    assert all(p.endswith(".") for p in parts)
    assert len(parts[0]) <= 110 and max(len(p) for p in parts) <= 220
    assert split_speech("") == [] and split_speech("Hi.") == ["Hi."]


def test_goal_tags_are_read_and_removed():
    from features import extract_goals
    text = ('Done.\n<goal add="Run a 10k" section="goal">Starting with 3 runs a week</goal>\n'
            '<goal id="g-abc" done="true">Booked for Oct 20</goal><goal>no id or title</goal>')
    clean, changes = extract_goals(text)
    assert clean.strip() == "Done."
    assert changes == [{"note": "Starting with 3 runs a week", "title": "Run a 10k", "section": "goal"},
                       {"note": "Booked for Oct 20", "id": "g-abc", "done": True}]


def test_goals_store(tmp_path):
    from features import Goals
    goals = Goals(tmp_path / "goals.json")
    g = goals.add("  Get   a pilot license ", "instructor is on it", "tracking")
    v = goals.version
    assert g["title"] == "Get a pilot license" and g["section"] == "tracking" and not g["done"]
    goals.update(g["id"], done=True, note="approved", section="nonsense")
    assert goals.get(g["id"])["done"] and goals.get(g["id"])["section"] == "tracking" and goals.version >= v
    assert f"[{g['id']}] (tracking, done) Get a pilot license — approved" in goals.context()
    assert Goals(tmp_path / "goals.json").list()[0]["note"] == "approved"      # saved on disk
    goals.delete(g["id"])
    assert goals.list() == [] and goals.context() == ""


def test_ideas_are_read_from_a_reply():
    from features import parse_ideas
    reply = 'Here you go:\n[{"title": "I can draft your weekly plan", "detail": "From your calendar.", ' \
            '"prompt": "Draft my plan for this week", "emoji": "🗓️"}, {"title": "no prompt"}]\nThanks'
    ideas = parse_ideas(reply)
    assert len(ideas) == 1 and ideas[0]["title"] == "I can draft your weekly plan" and ideas[0]["id"].startswith("i-")
    assert parse_ideas("no json here") == [] and parse_ideas("[not json") == []


def test_quiet_is_read_from_a_reply():
    from features import extract_quiet
    assert extract_quiet("Nothing new.\n<quiet/>") == ("Nothing new.", True)
    assert extract_quiet("Nothing new. <quiet></quiet>") == ("Nothing new.", True)
    assert extract_quiet("Two new roles.") == ("Two new roles.", False)


def test_say_is_read_from_a_siri_reply():
    from features import extract_say
    text, said = extract_say("<say>You have class at 12:45 and VISTA writing at 3:30.</say>\n\n- 12:45 Robotics class")
    assert said == "You have class at 12:45 and VISTA writing at 3:30."
    assert text == "You have class at 12:45 and VISTA writing at 3:30.\n\n- 12:45 Robotics class"   # the chat keeps both
    assert extract_say("No tag here.") == ("No tag here.", "")


def test_suggestion_is_read_from_a_reply():
    from features import extract_suggestion
    assert extract_suggestion("Done.\n<suggest>Now  book the\nflight</suggest>\n") == ("Done.", "Now book the flight")
    assert extract_suggestion("<suggest>Draft a repair request email to my landlord</suggest>")[1] == "Draft a repair request email to"
    assert extract_suggestion("<suggest> \"What's on my plate today\"</suggest>")[1] == "What's on my plate today"
    assert extract_suggestion("No tag here.") == ("No tag here.", "")


def test_chat_title_is_cleaned():
    from features import clean_title
    assert clean_title('\n"Weekend trip to Lisbon."\n') == "Weekend trip to Lisbon"
    assert clean_title("Greeting and general chat start") == "Greeting and general"
    assert clean_title("**Title: Tax deadline questions**") == "Tax deadline questions"


def test_notice_is_one_short_line():
    from features import clean_notice
    assert clean_notice('\n"Your flight to Lisbon is booked."\nMore text') == "Your flight to Lisbon is booked"
    assert clean_notice("**Notification: Needs OK to send the email**") == "Needs OK to send the email"
    assert len(clean_notice("word " * 40)) <= 64


def test_ideas_keep_a_short_ask():
    from features import parse_ideas
    ideas = parse_ideas('[{"title": "I can plan", "prompt": "Plan my week in detail", "ask": "Plan my week"}]')
    assert ideas[0]["ask"] == "Plan my week"


def test_reactions_are_rare_and_one_of_the_set():
    from features import REACT_EVERY, clean_reaction, react_chance
    assert react_chance("Thanks, that was perfect!", REACT_EVERY) > react_chance("Move the file to Downloads", REACT_EVERY) > 0
    assert react_chance("I passed the exam!!", REACT_EVERY - 1) == 0                  # just reacted in this chat
    assert react_chance("k", REACT_EVERY) == 0 and react_chance("word " * 400, REACT_EVERY) == 0
    assert clean_reaction("\U0001F389\n") == "\U0001F389" and clean_reaction("\u2764") == "\u2764\ufe0f"   # with or without VS16
    assert clean_reaction("none") is None and clean_reaction("\U0001F921") is None     # not in the set


def test_reaction_tag_is_read_from_a_reply():
    from features import extract_reaction
    assert extract_reaction("Love you too.\n<react>\u2764\ufe0f</react>\n<suggest>x</suggest>") == (
        "Love you too.\n\n<suggest>x</suggest>", ("\u2764\ufe0f", 0))
    assert extract_reaction('Done. <react back="1">\U0001F440</react>')[1] == ("\U0001F440", 1)
    assert extract_reaction("<react>heart</react>Ok") == ("Ok", None)                    # words, not an emoji
    assert extract_reaction("No tag here.") == ("No tag here.", None)


def test_restart_is_read_from_a_reply():
    from features import extract_restart
    assert extract_restart("Restarting now, back in a moment.\n<restart/>") == ("Restarting now, back in a moment.", True)
    assert extract_restart("Ok <restart></restart>") == ("Ok", True)
    assert extract_restart("Done.") == ("Done.", False)


def test_context_has_the_to_do_rule_when_there_is_a_task_list(tmp_path):
    """Live eval (2026-10-20): "I checked my passport expiry, it's fine" left the task open. The rule was only in
    Daily planning.md, which Milo reads only for planning work, so it now sits in the context."""
    settings = {"assistant_name": "Milo", "tone": "warm", "length": "short"}
    assert "To-do list" not in build_context(settings, "", tmp_path)
    (tmp_path / "Planner").mkdir()
    (tmp_path / "Planner" / "Tasks.md").write_text("# Tasks\n")
    ctx = build_context(settings, "", tmp_path)
    assert f'To-do list: "{tmp_path / "Planner" / "Tasks.md"}"' in ctx and "mark it done" in ctx


def test_plan_name_prefers_the_account_record():
    """Bug (2026-10-20): Settings said "Pro" on a Max 5x account (auth status keeps the plan from login time)."""
    from features import plan_name
    stale = {"subscriptionType": "pro"}
    assert plan_name({"organizationRateLimitTier": "default_claude_max_5x", "organizationType": "claude_max"}, stale) == "Max 5x"
    assert plan_name({"userRateLimitTier": "default_claude_max_20x"}, stale) == "Max 20x"
    assert plan_name({"organizationType": "claude_max"}, stale) == "Max"
    assert plan_name({}, stale) == "Pro"   # no account record: what auth status says
    assert plan_name({}, {}) == ""


def test_task_posts_list_when_which_task_and_the_message():
    from features import task_posts
    ts = datetime(2026, 11, 11, 8, 0).timestamp()
    out = task_posts([{"task": "Morning briefing", "ts": ts, "text": "Two meetings today."},
                      {"task": "Night check-in", "ts": ts + 3600, "text": "x" * 4000,
                       "instruction": "Ask how the day went. When he answers, add an entry to Daily log.md."}])
    assert out.startswith("[Wed Nov 11 08:00, Morning briefing]\nYour message:\nTwo meetings today.\n\n"
                          "[Wed Nov 11 09:00, Night check-in]\nThe task's instruction: Ask how the day went. When he "
                          "answers, add an entry to Daily log.md.\nYour message:\n")
    assert out.endswith(" [...]") and len(out) < 3400


def test_a_step_is_named_by_what_it_did():
    """'Terminal' told the user nothing (BEHAVIOR #97): a step names the files it read or changed."""
    from features import describe_step
    grep = ('grep -n -i -E "review|grading" "/Users/alex/Documents/Milo/Library/Planner/Tasks.md"; '
            'head -15 "/Users/alex/Documents/Milo/Library/Planner/Tasks.md"')
    assert describe_step("Bash", {"command": grep}) == ("Read Tasks.md", grep)
    edit = ("cd \"/Users/alex/Documents/Milo/Library/Planner\" && python3 - <<'E'\nL=open('Tasks.md').read()\n"
            "open('Tasks.md','w').write(L)\nE")
    assert describe_step("Bash", {"command": edit})[0] == "Edited Tasks.md"   # the name alone, after a cd
    assert describe_step("Bash", {"command": 'echo hi >> "$HOME/Documents/Milo/Library/Planner/Daily log.md"'})[0] == \
        "Edited Daily log.md"
    assert describe_step("Bash", {"command": "ls ~/Downloads", "description": "List downloads"}) == \
        ("List downloads", "ls ~/Downloads")
    assert describe_step("Bash", {"command": "date"}) == ("Ran a command", "date")
    assert describe_step("Edit", {"file_path": "/x/Instructions/Fitness.md"}) == ("Edited Fitness.md", "/x/Instructions/Fitness.md")
    assert describe_step("Read", {"file_path": "/x/a.pdf"})[0] == "Read a.pdf"
    assert describe_step("Grep", {"pattern": "gym"}) == ("Searched files", "gym")
    assert describe_step("mcp__milo-planner__day_view", {}) == ("", "")
