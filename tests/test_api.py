"""HTTP API with a temporary data folder and Keychain service. goose, Whisper and Chrome are not started."""

import asyncio
import importlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid

import keyring
import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    (data / "config.json").write_text(json.dumps({"token": TOKEN, "whisper_model": "/nonexistent",
                                                  "library_dir": str(data / "lib"), "browser_headless": True}))
    service = f"Milo-apitest-{uuid.uuid4().hex[:8]}"
    os.environ["MILO_DATA_DIR"], os.environ["MILO_KEYCHAIN_SERVICE"] = str(data), service
    import server
    server = importlib.reload(server)
    yield server
    for acct in server.hub.vault.accounts():
        server.hub.vault.delete(acct["id"])
    os.environ.pop("MILO_DATA_DIR"), os.environ.pop("MILO_KEYCHAIN_SERVICE")


@pytest.fixture
def client(srv):
    c = TestClient(srv.app)   # no "with": the lifespan (goose, whisper, chrome) does not run
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    return c


def test_token_is_required(srv):
    anon = TestClient(srv.app)
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/api/state", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert anon.get(f"/api/state?token={TOKEN}").status_code == 200
    assert anon.get("/").status_code == 200           # the app shell itself is public


def test_ws_rejects_bad_token(srv):
    anon = TestClient(srv.app)
    for path in ("/ws?token=wrong", "/ws/browser?token=wrong"):
        with pytest.raises(Exception):
            with anon.websocket_connect(path) as ws:
                ws.receive_json()


def test_state_includes_browser(client):
    st = client.get("/api/state").json()
    assert st["browser"]["controller"] == "milo" and "enabled" in st["browser"]


def test_accounts_crud_never_returns_secrets(client, srv):
    r = client.post("/api/accounts", json={"domain": "https://www.example.com", "username": "alex",
                                           "password": "Pa55-word!", "label": "Example"})
    assert r.status_code == 200
    acct = r.json()
    assert acct["domain"] == "example.com" and "Pa55-word!" not in r.text
    assert "Pa55-word!" not in client.get("/api/accounts").text
    assert "Pa55-word!" not in (srv.DATA / "accounts.json").read_text()
    assert client.patch(f"/api/accounts/{acct['id']}", json={"policy": "auto"}).json()["policy"] == "auto"
    assert client.patch(f"/api/accounts/{acct['id']}", json={"policy": "maybe"}).status_code == 400
    assert client.delete(f"/api/accounts/{acct['id']}").status_code == 200
    assert keyring.get_password(srv.KEYCHAIN_SERVICE, f"{acct['id']}:password") is None
    assert client.delete(f"/api/accounts/{acct['id']}").status_code == 404


def test_accounts_validation(client):
    assert client.post("/api/accounts", json={"domain": "x.com", "username": "a"}).status_code == 400


def test_schedules_api(client):
    bad = client.post("/api/schedules", json={"text": "x", "cron": "nope"})
    assert bad.status_code == 400
    item = client.post("/api/schedules", json={"text": "Stretch", "kind": "reminder", "cron": "0 15 * * *"}).json()
    assert item["kind"] == "task"                                                    # there are no reminders now
    assert client.patch(f"/api/schedules/{item['id']}", json={"enabled": False}).json()["enabled"] is False
    auto = client.patch(f"/api/schedules/{item['id']}", json={"auto_approve": True}).json()
    assert auto["auto_approve"] is True and auto["enabled"] is False                # the switch leaves it paused
    edited = client.patch(f"/api/schedules/{item['id']}", json={"text": "Stretch for 5 min", "title": "Stretch"}).json()
    assert (edited["id"], edited["text"], edited["title"], edited["cron"], edited["enabled"], edited["auto_approve"]) == (
        item["id"], "Stretch for 5 min", "Stretch", "0 15 * * *", False, True)        # in place; switch and settings kept
    assert client.patch(f"/api/schedules/{item['id']}", json={"cron": "nope"}).status_code == 400
    assert client.patch("/api/schedules/nope", json={"text": "x"}).status_code == 404
    assert any(s["id"] == item["id"] for s in client.get("/api/schedules").json())
    later = client.post("/api/schedules", json={"text": "Water", "cron": "*/5 * * * *"}).json()
    order = [s["id"] for s in client.get("/api/schedules").json()]
    assert order.index(item["id"]) < order.index(later["id"])                       # paused, soonest: still in place
    assert client.delete(f"/api/schedules/{later['id']}").status_code == 200
    assert client.delete(f"/api/schedules/{item['id']}").status_code == 200


def test_read_state_lives_on_the_mac(srv, client, monkeypatch):
    """Which chats are read is kept with the chat, so every device shows the same dots. A chat saved before the read
    marker existed counts as read; reading tells every open app (BEHAVIOR #92)."""
    hub, sent = srv.hub, []

    async def broadcast(ev):
        sent.append(ev)
    monkeypatch.setattr(hub, "broadcast", broadcast)
    old = srv.Conversation(**{"id": "rd-old", "title": "Old", "updated": 1000.0, "messages": []})   # saved before
    assert old.read == 1000.0 and old.to_json()["read"] == 1000.0
    hub.convs["rd-old"] = old
    conv = srv.Conversation("rd-1", updated=2000.0, read=1500.0)                                  # a reply since
    hub.convs["rd-1"] = conv
    listed = {c["id"]: c for c in client.get("/api/state").json()["conversations"]}
    assert listed["rd-1"]["read"] < listed["rd-1"]["updated"] and listed["rd-old"]["read"] == listed["rd-old"]["updated"]
    assert client.post("/api/conversations/rd-1/read", json={"at": 1800.0}).json()["read"] == 1800.0
    assert sent == [{"t": "read", "id": "rd-1", "read": 1800.0}]
    assert client.post("/api/conversations/rd-1/read", json={"at": 9999.0}).json()["read"] == 2000.0   # not past the chat
    client.post("/api/conversations/rd-1/read", json={"at": 1700.0})                                 # never goes back
    assert conv.read == 2000.0 and len(sent) == 2
    conv.updated = 2500.0
    assert client.post("/api/conversations/rd-1/read").json()["read"] == 2500.0                      # no body: all of it
    saved = next(c for c in hub.store.data if c["id"] == "rd-1")
    assert saved["read"] == 2500.0 and srv.Conversation(**saved).read == 2500.0                     # kept across restarts
    assert client.post("/api/conversations/nope/read").status_code == 404
    for cid in ("rd-old", "rd-1"):
        hub.convs.pop(cid)
    hub.save()


def test_only_the_users_stop_counts_as_stopped(srv, monkeypatch):
    """goose reports many finished tool turns as cancelled. Milo shows Stopped only after the user's Stop."""
    hub = srv.hub
    ids = iter(["stop-1", "stop-2"])

    async def nothing(*a, **k):
        pass

    async def new_session(servers):
        return next(ids)

    async def prompt(sid, blocks):
        hub.convs[sid].messages.append({"role": "assistant", "text": "Done.", "tools": [], "notes": [], "ts": 0})
        return {"stopReason": "cancelled"}
    for name, fn in [("new_session", new_session), ("ensure_running", nothing), ("prompt", prompt), ("cancel", nothing)]:
        monkeypatch.setattr(hub.goose, name, fn)
    monkeypatch.setattr(hub.goose, "is_loaded", lambda sid: True)
    monkeypatch.setattr(hub, "notify", nothing)

    async def turn(user_stops):
        conv = await hub.new_conversation()
        conv.running = True
        if user_stops:
            await hub.cancel(conv)
        await hub._run(conv, "hi", False)
        return conv.messages[-1]["notes"]
    assert asyncio.run(turn(False)) == []
    assert asyncio.run(turn(True)) == [{"kind": "stopped", "text": "Stopped"}]


def fake_goose(hub, monkeypatch, reply="Done.", used=1000):
    """A goose that answers every prompt and reports its context size. Returns the (session, prompt) list."""
    ids, prompts = iter(f"fg-{i}" for i in range(100)), []

    async def nothing(*a, **k):
        pass

    async def new_session(servers):
        return next(ids)

    async def prompt(sid, blocks):
        prompts.append((sid, blocks[0]["text"]))
        await hub.on_update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"text": reply}})
        await hub.on_update(sid, {"sessionUpdate": "usage_update", "used": used, "size": 1000000})
        return {"stopReason": "end_turn", "usage": {"totalTokens": used}}
    for name, fn in [("new_session", new_session), ("ensure_running", nothing), ("prompt", prompt), ("cancel", nothing)]:
        monkeypatch.setattr(hub.goose, name, fn)
    monkeypatch.setattr(hub.goose, "is_loaded", lambda sid: True)
    monkeypatch.setattr(hub, "notify", nothing)
    return prompts


def test_chunks_say_where_they_go(srv, monkeypatch):
    """A phone that reads the chat mid-reply plays the chunks that came meanwhile again: "at" (in the app's UTF-16
    units) lets it skip the ones it has."""
    hub = srv.hub
    sent = []

    async def broadcast(ev):
        sent.append(ev)
    monkeypatch.setattr(hub, "broadcast", broadcast)

    async def go():
        conv = await hub.new_conversation()
        for t in ["Hi \U0001F600 ", "there", " again"]:
            await hub.on_update(conv.sid, {"sessionUpdate": "agent_message_chunk", "content": {"text": t}})
        conv.messages.append({"role": "user", "text": "next", "ts": 0})   # a new reply starts at 0
        await hub.on_update(conv.sid, {"sessionUpdate": "agent_message_chunk", "content": {"text": "ok"}})
    fake_goose(hub, monkeypatch)
    asyncio.run(go())
    assert [(e["text"], e["at"]) for e in sent if e["t"] == "chunk"] == [("Hi \U0001F600 ", 0), ("there", 6), (" again", 11), ("ok", 0)]


def test_a_big_chat_compacts_into_a_new_session(srv, client, monkeypatch):
    """Over compact_at, the session writes a summary and the chat goes on in a new session that starts from it."""
    hub = srv.hub
    monkeypatch.setitem(srv.CFG, "compact_at", 5000)
    prompts = fake_goose(hub, monkeypatch, reply="Here is the plan.", used=6000)

    async def go():
        conv = await hub.new_conversation(title="Plans")
        first = conv.sid
        conv.running = True
        conv.messages.append({"role": "user", "text": "Plan my week", "ts": 0})
        await hub._run(conv, "Plan my week", False)
        assert conv.compacting and conv.sid == first
        await conv.compacting                                                     # runs after the turn
        assert conv.sid != first and conv.id == first and conv.used == 0 and conv.compacting is None
        assert prompts[-1][0] == first and "moving it to a new session" in prompts[-1][1]
        assert [m["text"] for m in conv.messages] == ["Plan my week", "Here is the plan."]   # not the summary
        assert conv.messages[-1]["notes"] == []                                   # silent: no line, no brief
        await hub.on_update(first, {"sessionUpdate": "agent_message_chunk", "content": {"text": "late"}})
        assert conv.messages[-1]["text"] == "Here is the plan."                  # the old session is gone
        monkeypatch.setitem(srv.CFG, "compact_at", 10 ** 9)
        conv.running = True
        await hub._run(conv, "And Friday?", False)
        sid, text = prompts[-1]
        assert sid == conv.sid and text.startswith("And Friday?") and "<milo_context>" in text
        assert "Your summary of the chat so far:\nHere is the plan." in text and "User: Plan my week" in text
        assert conv.carry is None and conv.used == 6000
        assert hub.conv_of(conv.sid) is conv and hub.conv_of(first) is None
        return conv
    conv = asyncio.run(go())
    saved = srv.Conversation(**conv.to_json())                                   # survives a restart
    assert (saved.id, saved.sid, saved.used) == (conv.id, conv.sid, 6000)
    conv.running = True
    assert client.post(f"/api/conversations/{conv.id}/compact").status_code == 409
    conv.running = False
    r = client.post(f"/api/conversations/{conv.id}/compact")                    # no button: the live suite uses it
    assert r.status_code == 200 and r.json()["used"] == 0 and r.json()["compacting"] is False
    hub.convs.pop(conv.id)


SUMMARY = ("Brief: We planned your week. Friday stays open for the trip.\n\n"
           "The user asked for a week plan. Monday: gym. Friday: kept free for the Lisbon trip.")


def summary_goose(hub, monkeypatch, used=40000):
    """fake_goose, but the compaction prompt gets SUMMARY back (a brief line, then the summary)."""
    prompts = fake_goose(hub, monkeypatch, reply="Here is the plan.", used=used)
    plain = hub.goose.prompt

    async def prompt(sid, blocks):
        if "moving it to a new session" not in blocks[0]["text"]:
            return await plain(sid, blocks)
        prompts.append((sid, blocks[0]["text"]))
        await hub.on_update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"text": SUMMARY}})
        return {"stopReason": "end_turn"}
    monkeypatch.setattr(hub.goose, "prompt", prompt)
    return prompts


def test_compacting_is_silent(srv, client, monkeypatch):
    """Like talking to a person: a compaction leaves the chat as it was, with no line, brief or note, and the new
    session gets the whole summary."""
    hub = srv.hub
    prompts = summary_goose(hub, monkeypatch)
    sent = []

    async def record(ev):
        sent.append(ev)
    monkeypatch.setattr(hub, "broadcast", record)

    async def go():
        conv = await hub.new_conversation(title="Plans")
        conv.running = True
        conv.messages.append({"role": "user", "text": "Plan my week", "ts": 0})
        await hub._run(conv, "Plan my week", False)
        return conv
    conv = asyncio.run(go())
    n, before = len(prompts), json.dumps(conv.messages)
    r = client.post(f"/api/conversations/{conv.id}/compact")
    assert r.status_code == 200 and len(prompts) == n + 1                      # one summary prompt, nothing more
    assert json.dumps(conv.messages) == before and not [e for e in sent if e["t"] in ("note", "toast")]
    assert "Friday: kept free for the Lisbon trip." in conv.carry
    assert "Brief" not in srv.COMPACT_PROMPT
    hub.convs.pop(conv.id)


def test_the_word_compact_is_an_ordinary_message(srv, client, monkeypatch):
    """No compact command: "compact" typed or said to Siri goes to Milo like any message."""
    hub = srv.hub
    prompts = summary_goose(hub, monkeypatch, used=2000)

    async def go():
        conv = await hub.main_conv()
        conv.messages[:] = []
        sid = conv.sid
        await hub.submit(conv, "compact", False)
        await conv.done.wait()
        assert conv.sid == sid and [m["text"] for m in conv.messages] == ["compact", "Here is the plan."]
        assert prompts[-1][1].startswith("compact") and "moving it to a new session" not in prompts[-1][1]
        hub.convs.pop(conv.id)
    asyncio.run(go())


def test_each_task_run_starts_a_new_session(srv, monkeypatch):
    """A recurring task's runs share one chat in the app, but not one Claude session: old runs are not re-read."""
    hub = srv.hub
    prompts = fake_goose(hub, monkeypatch, used=200000)
    task = hub.scheduler.add(title="Sweep", text="Run a sweep", cron="0 * * * *")

    async def go():
        conv = await hub.schedule_conversation(task)
        first = conv.sid
        for _ in range(2):
            await hub.submit(conv, "Run a sweep", False, scheduled=True)
            await conv.done.wait()
        assert [p[0] for p in prompts] == [first, conv.sid] and conv.sid != first
        assert conv.compacting is None                                              # the next run is fresh anyway
        assert all("<milo_context>" in p[1] for p in prompts)
        await hub.submit(conv, "Skip Acme next time", False)                       # the user's reply: same session
        await conv.done.wait()
        assert prompts[-1][0] == conv.sid
        return conv
    conv = asyncio.run(go())
    if conv.compacting:
        conv.compacting.cancel()
    hub.convs.pop(conv.id)
    hub.scheduler.remove(task["id"])


def test_idle_sessions_are_closed(srv, monkeypatch):
    """Each goose session keeps a Claude Code process (about 400 MB; 32 of them hung the Mac on 2026-10-21). Old
    sessions and quiet side chats are closed; the main chat and busy or recent chats keep theirs."""
    hub = srv.hub
    closed = []

    async def close_session(sid):
        closed.append(sid)
    old = time.time() - srv.RELEASE_IDLE - 60
    kinds = {"rs-main": {"main": True, "updated": old}, "rs-quiet": {"updated": old},
             "rs-recent": {"updated": time.time()}, "rs-busy": {"updated": old}, "rs-compacting": {"updated": old}}
    for cid, kw in kinds.items():
        hub.convs[cid] = srv.Conversation(cid, **kw)
    hub.convs["rs-busy"].running = True
    hub.convs["rs-compacting"].compacting = True
    monkeypatch.setattr(hub.goose, "loaded", lambda: {*kinds, "rs-before-compacting"})
    monkeypatch.setattr(hub.goose, "close_session", close_session)
    try:
        asyncio.run(hub.release_sessions())
        assert sorted(closed) == ["rs-before-compacting", "rs-quiet"]
    finally:
        for cid in kinds:
            hub.convs.pop(cid)


def test_task_runs_are_logged(srv, client, monkeypatch):
    """Every run of a task is in its history, which the Upcoming tab shows when you tap the task."""
    hub = srv.hub

    async def new_session(servers):
        return "hist-1"

    async def nothing(*a, **k):
        pass
    monkeypatch.setattr(hub.goose, "new_session", new_session)
    monkeypatch.setattr(hub.goose, "cancel", nothing)
    monkeypatch.setattr(hub, "notify", nothing)
    monkeypatch.setattr(hub, "_run", nothing)
    task = hub.scheduler.add(title="Sweep", text="Run a sweep", cron="*/30 * * * *")
    asyncio.run(hub.fire_schedule(task))
    asyncio.run(hub.fire_schedule(task))                                            # fires while the first one runs
    assert [r["status"] for r in hub.scheduler.history_of(task["id"])] == ["queued", "running"]
    conv = hub.convs["hist-1"]
    conv.messages.insert(1, {"role": "assistant", "text": "Checking LinkedIn.Applied to 1 job.", "notes": [], "ts": 0,
                             "tools": [{"id": "t1", "at": len("Checking LinkedIn.")}]})     # above the waiting run; the summary is the answer
    asyncio.run(hub._finish(conv, "end_turn", None, False))
    asyncio.run(hub.cancel(conv))                                                   # the waiting run never starts
    runs = client.get(f"/api/schedules/{task['id']}/history").json()
    assert [(r["status"], r["summary"], r["conv"]) for r in runs] == [
        ("stopped", "", "hist-1"), ("done", "Applied to 1 job.", "hist-1")]
    assert client.get("/api/schedules/nope/history").status_code == 404
    conv.running = False
    hub.scheduler.remove(task["id"])


def test_a_task_runs_out_of_sight_and_talks_in_the_main_chat(srv, monkeypatch):
    """Every run of a task works in the task's one hidden chat and saves its result in its Library folder. Its answer
    comes to the main chat as Milo's own message (no "ran" line, no steps, weather cards kept), with the alert; a quiet
    run says nothing. The main session hears about the message with the user's next prompt."""
    hub = srv.hub
    ids, sent = iter(["rec-1", "rec-2", "rec-main"]), []

    async def new_session(servers):
        return next(ids)

    async def notify(*a, **k):
        sent.append(a)
    monkeypatch.setattr(hub.goose, "new_session", new_session)
    monkeypatch.setattr(hub, "notify", notify)
    prompts = []

    async def no_run(conv, text, voice, task=False):
        prompts.append(text)
    monkeypatch.setattr(hub, "_run", no_run)
    other = asyncio.run(hub.new_conversation(title="Other"))

    task = hub.scheduler.add(title="Daily brief", text="Brief me", cron="0 8 * * *")
    tconv = asyncio.run(hub.schedule_conversation(task))
    assert not hub.auto_approves(tconv.id)
    hub.scheduler.set_auto_approve(task["id"], True)
    assert hub.auto_approves(tconv.id) and not hub.auto_approves(other.id) and not hub.auto_approves(None)

    async def run_task():
        await hub.submit(tconv, "Brief me", False, scheduled=True)
        await asyncio.sleep(0)                                                      # let the run start
    async def finish():   # with the post it starts in the background
        await hub._finish(tconv, "end_turn", None, False)
        await asyncio.gather(*hub.side_tasks)
    main = asyncio.run(hub.main_conv())
    main.messages[:], main.inbox[:] = [], []
    assert hub.chat_id(tconv.id) == main.id and hub.chat_id(other.id) == other.id   # an alert opens the main chat
    asyncio.run(run_task())
    assert tconv.messages[-1]["task"] == "Daily brief" and tconv.summary()["preview"] == "Daily brief ran"
    assert prompts[-1].startswith("Brief me\n\n") and 'scheduled task "Daily brief"' in prompts[-1]   # not the user's words
    tconv.messages.append({"role": "assistant", "text": "Let me look.Three meetings today.", "notes": [], "ts": 0,
                           "tools": [{"id": "t0", "title": "Calendar", "at": len("Let me look.")}]})
    asyncio.run(finish())
    [run] = (hub.library.root / "Recurring tasks" / "Daily brief").glob("*.md")    # one file per run
    assert run.read_text().startswith("# Daily brief, ") and "Three meetings today." in run.read_text()
    assert tconv.messages[-1]["notes"] == [{"kind": "saved", "text": "Recurring tasks/Daily brief"}]
    [post] = main.messages                                                          # only the answer, no steps
    assert {**post, "ts": 0} == {"role": "assistant", "text": "Three meetings today.", "tools": [], "notes": [],
                                 "ts": 0, "from_task": "Daily brief"}
    assert sent[-1] == ("Daily brief", "Three meetings today.", main.id)
    run.unlink()                                                                    # a run with a weather card
    card = {"id": "t1", "title": "Weather", "weather": {"location": "Portland, OR", "now": {}}}
    tconv.messages.append({"role": "assistant", "text": "Rain at 10.", "notes": [], "ts": 0, "tools": [card]})
    asyncio.run(finish())
    [run] = (hub.library.root / "Recurring tasks" / "Daily brief").glob("*.md")    # the Library shows it as the card
    assert '```weather\n{"location":"Portland, OR","now":{}}\n```\n\nRain at 10.' in run.read_text()
    assert main.messages[-1]["text"] == "Rain at 10." and main.messages[-1]["tools"] == [card]   # the card comes too
    blocks = hub._prompt_blocks(main, "What was that about rain?", False)[0]["text"]
    assert blocks.startswith("What was that about rain?") and "from scheduled tasks" in blocks
    assert ", Daily brief]\nThe task's instruction: Brief me\nYour message:\nThree meetings today." in blocks
    assert "Your message:\nRain at 10." in blocks and "it finishes that task" in blocks
    assert main.inbox == [] and "from scheduled tasks" not in hub._prompt_blocks(main, "ok", False)[0]["text"]

    alerts = len(sent)                                                              # a run with nothing new: <quiet/>
    tconv.running = False                                                           # the last run ended (not queued)
    asyncio.run(hub.submit(tconv, "Brief me", False, scheduled=True))
    tconv.messages.append({"role": "assistant", "text": "Nothing new. <quiet/>", "tools": [], "notes": [], "ts": 0})
    asyncio.run(finish())
    assert tconv.messages[-1]["text"] == "Nothing new." and tconv.messages[-1]["notes"] == []
    assert len(sent) == alerts and len(list((hub.library.root / "Recurring tasks" / "Daily brief").glob("*.md"))) == 1
    assert len(main.messages) == 2 and main.inbox == []                            # the main chat hears nothing

    pause = f'Paused it.<schedule id="{task["id"]}" enabled="false"></schedule>'
    tconv.messages.append({"role": "assistant", "text": pause, "tools": [], "notes": [], "ts": 0})
    asyncio.run(finish())                                                           # a run can't switch itself off
    assert tconv.messages[-1]["text"] == "Paused it." and hub.scheduler.store.data[-1]["enabled"] is True
    tconv.running = False
    asyncio.run(hub.submit(tconv, "Pause the daily brief", False))                 # the user asks: it pauses
    tconv.messages.append({"role": "assistant", "text": pause, "tools": [], "notes": [], "ts": 0})
    asyncio.run(hub._finish(tconv, "end_turn", None, False))
    assert hub.scheduler.store.data[-1]["enabled"] is False
    assert tconv.messages[-1]["notes"][0]["text"] == "Paused Daily brief"

    async def change(answer):   # Milo changes a task: it waits for the user's OK
        tconv.messages.append({"role": "assistant", "text": f'Asked.<schedule id="{task["id"]}" cron="0 * * * *"></schedule>',
                               "tools": [], "notes": [], "ts": 0})
        await hub._finish(tconv, "end_turn", None, False)
        await asyncio.sleep(0)
        [approval] = [a for a in hub.approvals.values() if a["conv"] == tconv.id]
        assert approval["title"] == "Change Daily brief?" and approval["command"] == "When: Every day at 8:00 AM → Every hour"
        assert hub.scheduler.get(task["id"])["cron"] == "0 8 * * *"
        await hub.resolve_approval(approval["id"], answer)
        await asyncio.gather(*hub.side_tasks)
        return tconv.messages[-1]["notes"][-1]["text"]
    assert asyncio.run(change("reject_once")) == "Did not change Daily brief"
    assert hub.scheduler.get(task["id"])["cron"] == "0 8 * * *"
    assert asyncio.run(change("allow_once")) == "Changed Daily brief"
    edited = hub.scheduler.get(task["id"])
    assert edited["cron"] == "0 * * * *" and edited["enabled"] is False and len(hub.scheduler.store.data) == 1
    hub.scheduler.remove(task["id"])
    hub.convs.pop("rec-1"), hub.convs.pop("rec-2"), hub.convs.pop(main.id)


def test_a_task_message_waits_for_the_main_chats_turn(srv, monkeypatch):
    """A task's message never lands between the user's message and Milo's reply in the main chat: it waits for the turn
    to end."""
    hub = srv.hub
    fake_goose(hub, monkeypatch)
    sent = []

    async def record(ev):
        sent.append(ev)
    monkeypatch.setattr(hub, "broadcast", record)

    async def go():
        main = await hub.main_conv()
        main.messages[:], main.inbox[:] = [{"role": "user", "text": "Plan my day", "ts": 1}], []
        main.running = True
        main.done.clear()
        post = asyncio.create_task(hub.post_to_main("Email check", {"tools": []}, "Dr. Wren wrote back."))
        await asyncio.sleep(0.05)
        assert [m["text"] for m in main.messages] == ["Plan my day"] and not post.done()
        main.messages.append({"role": "assistant", "text": "Here is your day.", "tools": [], "notes": [], "ts": 2})
        main.running = False
        main.done.set()
        await post
        assert [m["text"] for m in main.messages] == ["Plan my day", "Here is your day.", "Dr. Wren wrote back."]
        assert [e["message"]["text"] for e in sent if e["t"] == "message"] == ["Dr. Wren wrote back."]
        assert [p["task"] for p in main.inbox] == ["Email check"]
        saved = srv.Conversation(**main.to_json())                                  # survives a restart
        assert saved.inbox == main.inbox
        hub.convs.pop(main.id)
    asyncio.run(go())


def test_memory_api(client):
    client.put("/api/memory", json={"text": "- Likes tea"})
    assert client.get("/api/memory").json()["text"] == "- Likes tea"


def test_settings_validation(client, srv):
    assert client.put("/api/settings", json={"permission_mode": "yolo"}).status_code == 400
    assert client.put("/api/settings", json={"voice_rate": 999}).json()["voice_rate"] == 300
    assert client.put("/api/settings", json={"token": "hijack"}).status_code == 200   # ignored: not editable
    assert client.get("/api/settings").json().get("token") is None
    assert client.put("/api/settings", json={"voice_rate": "fast"}).status_code == 400
    # a blank name would leave the header empty; a long one is cut so it fits there
    assert client.put("/api/settings", json={"assistant_name": "   "}).json()["assistant_name"] == "Milo"
    assert len(client.put("/api/settings", json={"assistant_name": "Milo " * 30}).json()["assistant_name"]) == 40
    assert client.put("/api/settings", json={"assistant_name": "  Ada  ", "tone": ""}).json()["tone"] == srv.DEFAULTS["tone"]
    client.put("/api/settings", json={"assistant_name": "Milo"})


def test_usage_reads_claude_codes_usage_command(srv, client, monkeypatch):
    calls = []

    async def fake_cli(*args, timeout=30):
        calls.append(args)
        if args[0] == "auth":
            return json.dumps({"loggedIn": True, "email": "me@example.com", "subscriptionType": "pro"})
        return json.dumps({"type": "result", "local_command": "usage", "result":
                           "Current session: 55% used · resets Oct 18 at 3:09am (America/New_York)\n"
                           "Current week (all models): 44% used · resets Oct 20 at 3am (America/New_York)"})

    monkeypatch.setattr(srv, "claude_cli", fake_cli)
    monkeypatch.setitem(srv.USAGE, "at", 0.0)
    u = client.get("/api/usage").json()
    assert u["plan"] == "Pro" and u["email"] == "me@example.com" and "at" not in u
    assert [(l["label"], l["used"]) for l in u["limits"]] == [("This session", 55), ("This week (all models)", 44)]
    assert ("-p", "/usage") == calls[0][:2] and "--no-session-persistence" in calls[0]
    client.get("/api/usage")
    assert len(calls) == 2   # reused within USAGE_TTL

    async def broken(*args, timeout=30):
        raise RuntimeError("not signed in")

    monkeypatch.setattr(srv, "claude_cli", broken)
    monkeypatch.setitem(srv.USAGE, "at", 0.0)
    r = client.get("/api/usage")
    assert r.status_code == 502 and "not signed in" in r.json()["detail"]


def test_library_blocks_traversal(client):
    assert client.get("/api/library/file", params={"path": "../config.json"}).status_code == 404


def test_picture_route_serves_only_pictures_in_the_library_or_temp(client, srv, tmp_path):
    """#76: a reply's picture by full path (with spaces) in the Library or Temp; nothing else on the Mac."""
    lib, temp = srv.hub.library.root.resolve(), srv.hub.temp.resolve()
    assert temp == lib.parent / "Temp" and temp.is_dir()
    (lib / "Calories and weight.png").write_bytes(b"\x89PNG lib")
    (temp / "Plots").mkdir(exist_ok=True)
    (temp / "Plots" / "Sleep (week).png").write_bytes(b"\x89PNG tmp")
    (temp / "plot.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (temp / "notes.txt").write_text("secret")
    (lib / "notes.txt").write_text("secret")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG out")
    (temp / "link.png").symlink_to(outside)   # a link out of Temp
    get = lambda p, **kw: client.get("/api/picture", params={"path": p}, **kw)
    for path, body in [(str(lib / "Calories and weight.png"), b"\x89PNG lib"), ("Calories and weight.png", b"\x89PNG lib"),
                       (str(temp / "Plots" / "Sleep (week).png"), b"\x89PNG tmp")]:
        r = get(path)
        assert r.status_code == 200 and r.content == body, path
        assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
        assert "attachment" not in r.headers.get("content-disposition", "")
    assert get(str(temp / "plot.svg")).headers["content-security-policy"] == "sandbox"   # an SVG never runs as the app
    for bad in [str(temp / "notes.txt"), str(lib / "notes.txt"), "notes.txt", "../config.json", "../Temp/../config.json",
                str(lib / ".." / "config.json"), str(srv.DATA / "config.json"), str(outside), str(temp / "link.png"),
                "../outside.png", str(lib / "missing.png"), "/etc/passwd", "~/.ssh/id_rsa", "a\0.png", ""]:
        assert get(bad).status_code == 404, bad
    anon = TestClient(srv.app)
    assert anon.get("/api/picture", params={"path": "Calories and weight.png"}).status_code == 401
    assert anon.get("/api/picture", params={"path": "Calories and weight.png", "token": TOKEN}).status_code == 200


def test_picture_route_serves_screenshots_from_the_browsers_old_output_folder(client, srv, tmp_path, monkeypatch):
    """#85: a reply sent before the fix shows a screenshot from milo/.playwright-mcp. Its pictures load; its snapshots
    and console logs don't."""
    old = tmp_path / ".playwright-mcp"
    old.mkdir()
    monkeypatch.setattr(srv, "OLD_OUTPUT", old)
    (old / "bbcnews.png").write_bytes(b"\x89PNG shot")
    (old / "console-2026-10-22.log").write_text("log")
    (old / "page.yml").write_text("snapshot")
    get = lambda p: client.get("/api/picture", params={"path": p})
    r = get(str(old / "bbcnews.png"))
    assert r.status_code == 200 and r.content == b"\x89PNG shot" and r.headers["content-type"] == "image/png"
    for bad in [str(old / "console-2026-10-22.log"), str(old / "page.yml"), str(old / ".." / "outside.png"),
                str(old / ".." / ".." / "data" / "config.json")]:
        assert get(bad).status_code == 404, bad


def test_old_plots_leave_temp(srv):
    from features import clean_temp
    temp = srv.hub.temp
    (temp / "Old").mkdir(exist_ok=True)
    old, new = temp / "Old" / "old.png", temp / "new.png"
    old.write_bytes(b"x"), new.write_bytes(b"x")
    os.utime(old, (time.time() - 31 * 86400,) * 2)
    assert clean_temp(temp) == 1
    assert not old.exists() and not (temp / "Old").exists() and new.exists() and temp.is_dir()


def test_library_file_downloads_as_attachment(client, srv):
    lib = srv.hub.library.root
    (lib / "Dl").mkdir(parents=True, exist_ok=True)
    (lib / "Dl" / "résumé v2.pdf").write_bytes(b"%PDF-1")
    r = client.get("/api/library/file", params={"path": "Dl/résumé v2.pdf", "download": 1})
    assert r.status_code == 200 and r.content == b"%PDF-1"
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment") and "filename*=utf-8''r%C3%A9sum%C3%A9%20v2.pdf" in cd
    # iOS would preview a PDF in place of the app: a download is a type no browser shows inline
    assert r.headers["content-type"] == "application/octet-stream" and r.headers["x-content-type-options"] == "nosniff"
    inline = client.get("/api/library/file", params={"path": "Dl/résumé v2.pdf"})
    assert inline.headers["content-type"] == "application/pdf" and "attachment" not in inline.headers.get("content-disposition", "")
    anon = TestClient(srv.app)
    assert anon.get("/api/library/file", params={"path": "Dl/résumé v2.pdf", "download": 1}).status_code == 401
    assert anon.get("/api/library/file", params={"path": "Dl/résumé v2.pdf", "download": 1, "token": TOKEN}).status_code == 200


def test_library_folder_downloads_as_zip(client, srv, tmp_path):
    import io
    import zipfile
    lib = srv.hub.library.root
    (lib / "Zip Me" / "Sub").mkdir(parents=True, exist_ok=True)
    (lib / "Zip Me" / "a.txt").write_text("alpha")
    (lib / "Zip Me" / "Sub" / "b.png").write_bytes(b"\x89PNG" + bytes(range(256)) * 50)
    (lib / "Zip Me" / ".hidden").write_text("no")
    (tmp_path / "secret.txt").write_text("outside")
    (lib / "Zip Me" / "escape.txt").symlink_to(tmp_path / "secret.txt")   # a link out of the Library stays out
    (lib / "Zip Me" / "outdir").symlink_to(tmp_path, target_is_directory=True)
    (lib / "Zip Me" / "locked.txt").write_text("locked")
    (lib / "Zip Me" / "locked.txt").chmod(0)                            # unreadable: left out, the rest still comes
    try:
        r = client.get("/api/library/zip", params={"path": "Zip Me"})
    finally:
        (lib / "Zip Me" / "locked.txt").chmod(0o644)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == "attachment; filename=\"Zip Me.zip\"; filename*=utf-8''Zip%20Me.zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.testzip() is None
    expect = ["Zip Me/Sub/b.png", "Zip Me/a.txt"] + ([] if os.geteuid() else ["Zip Me/locked.txt"])
    assert sorted(z.namelist()) == expect
    assert z.read("Zip Me/a.txt") == b"alpha" and z.read("Zip Me/Sub/b.png").startswith(b"\x89PNG")
    assert client.get("/api/library/zip", params={"path": "Zip Me", "check": 1}).json()["files"] == 3   # readable again
    assert TestClient(srv.app).get("/api/library/zip", params={"path": "Zip Me"}).status_code == 401
    assert TestClient(srv.app).get("/api/library/zip", params={"path": "Zip Me", "token": TOKEN}).status_code == 200


def test_library_zip_blocks_traversal_and_limits(client, srv, tmp_path, monkeypatch):
    lib = srv.hub.library.root
    (lib / "Big").mkdir(parents=True, exist_ok=True)
    (lib / "Big" / "a.txt").write_text("12345")
    (lib / "Away").symlink_to(tmp_path, target_is_directory=True)
    for bad in ("..", "../", "Big/../..", "/etc", "", ".", "Away", "Big/a.txt", "Nope"):
        assert client.get("/api/library/zip", params={"path": bad}).status_code == 404, bad
    (lib / "Empty" / ".git").mkdir(parents=True, exist_ok=True)
    (lib / "Empty" / ".git" / "x").write_text("x")
    assert client.get("/api/library/zip", params={"path": "Empty"}).json()["detail"] == "folder is empty"
    monkeypatch.setattr(srv, "ZIP_MAX_BYTES", 4)
    r = client.get("/api/library/zip", params={"path": "Big", "check": 1})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_library_favorites(client, srv):
    lib = srv.hub.library.root
    (lib / "Fav" / "Sub").mkdir(parents=True, exist_ok=True)
    (lib / "Fav" / "a.pdf").write_bytes(b"a")
    (lib / "Fav" / "Sub" / "b.md").write_text("b")
    put = lambda **body: client.put("/api/library/favorites", json=body)
    assert put(path="Fav/a.pdf", kind="file", on=True).status_code == 200
    favs = put(path="Fav/", kind="folder", on=True).json()   # the same folder as "Fav"
    assert [(f["kind"], f["path"]) for f in favs] == [("folder", "Fav"), ("file", "Fav/a.pdf")]
    assert favs[0]["count"] == 2 and favs[1]["name"] == "a.pdf" and favs[1]["size"] == 1
    assert put(path="../config.json", kind="file", on=True).status_code == 404   # outside the Library
    assert put(path="Fav/nope.pdf", kind="file", on=True).status_code == 404
    assert put(path="Fav", kind="disk", on=True).status_code == 400
    client.delete("/api/library/file", params={"path": "Fav/a.pdf"})   # a deleted file loses its star
    (lib / "Fav" / "a.pdf").write_bytes(b"new")
    assert [f["path"] for f in client.get("/api/library/favorites").json()] == ["Fav"]
    assert put(path="Fav", kind="folder", on=False).json() == []


def test_browser_control_and_navigate_rules(client):
    assert client.post("/api/browser/navigate", json={"url": "example.com"}).status_code == 409
    assert client.post("/api/browser/control", json={"action": "take"}).json()["controller"] == "user"
    assert client.post("/api/browser/control", json={"action": "release"}).json()["controller"] == "milo"
    assert client.post("/api/browser/control", json={"action": "dance"}).status_code == 400


def test_mcp_endpoint_is_not_open(srv):
    anon = TestClient(srv.app)
    assert anon.post("/mcp/browser", json={}).status_code == 401
    assert anon.post("/mcp/browser", json={}, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


def test_mcp_servers_carry_key_and_auth(srv):
    servers, key = srv.hub.mcp_servers()
    assert servers[0]["name"] == "milo-browser" and f"k={key}" in servers[0]["url"]
    assert servers[0]["headers"][0]["value"] == f"Bearer {srv.CFG['browser_key']}"
    srv.hub.mcp_keys[key] = "conv-1"
    assert srv.hub.conv_for_key(key) == "conv-1"


async def test_permission_prompts_for_browser_tools_are_auto_allowed(srv):
    opts = [{"optionId": "allow_always"}, {"optionId": "allow_once"}, {"optionId": "reject_once"}]
    assert await srv.hub.on_permission("s", {"title": "mcp: milo-browser  browser_click"}, opts) == "allow_once"
    assert srv.hub.approvals == {}


async def test_approval_roundtrip(srv):
    task = asyncio.create_task(srv.hub.request_approval("s", "Click Buy now on shop.test?", "detail",
                                                        ["allow_once", "allow_site", "reject_once"]))
    await asyncio.sleep(0.05)
    aid, approval = next(iter(srv.hub.approvals.items()))
    assert approval["options"] == ["allow_once", "allow_site", "reject_once"]
    await srv.hub.resolve_approval(aid, "allow_site")
    assert await task == "allow_site"
    assert srv.hub.activity.recent()[0]["status"] == "allowed on this site"
    with pytest.raises(Exception):
        await srv.hub.resolve_approval(aid, "allow_once")   # already answered


async def test_a_repeated_request_reuses_the_answer(srv):
    hub = srv.hub
    opts = [{"optionId": o} for o in ("allow_always", "allow_once", "reject_once")]
    call = {"title": "Terminal", "toolCallId": "t1", "rawInput": {"command": "kill 123"}}
    task = asyncio.create_task(hub.on_permission("s", call, opts))
    await asyncio.sleep(0.05)
    await hub.resolve_approval(next(iter(hub.approvals)), "reject_once")
    assert await task == "reject_once"
    assert await hub.on_permission("s", {**call, "toolCallId": "t2"}, opts) == "reject_once" and hub.approvals == {}
    other = asyncio.create_task(hub.on_permission("s", {**call, "rawInput": {"command": "kill 456"}}, opts))
    await asyncio.sleep(0.05)
    assert len(hub.approvals) == 1                # a different command still asks
    await hub.resolve_approval(next(iter(hub.approvals)), "allow_once")
    assert await other == "allow_once"
    hub.answered.clear()


async def test_unattended_task_card_is_denied_after_a_while(srv, monkeypatch):
    hub = srv.hub
    monkeypatch.setitem(srv.CFG, "unattended_approval_minutes", 0.001)
    monkeypatch.setattr(hub, "auto_approves", lambda cid: cid == "task-chat")
    assert await hub.request_approval("task-chat", "Run rm?", "rm x", ["allow_once", "reject_once"]) == "reject_once"
    assert hub.approvals == {} and hub.activity.recent()[0]["status"] == "denied (no answer)"
    task = asyncio.create_task(hub.request_approval("other", "Run rm?", "rm x", ["allow_once", "reject_once"]))
    await asyncio.sleep(0.2)
    assert not task.done()                      # other chats wait for the user
    await hub.resolve_approval(next(iter(hub.approvals)), "allow_once")
    assert await task == "allow_once"


async def test_reads_pass_writes_ask_and_always_becomes_a_rule(srv):
    hub = srv.hub
    opts = [{"optionId": o} for o in ("allow_always", "allow_once", "reject_once", "reject_always")]
    read = {"title": "mcp: claude.ai Gmail  search_threads", "rawInput": {}}
    assert await hub.on_permission("s", read, opts) == "allow_once" and hub.approvals == {}

    write = {"title": "mcp: claude.ai Gmail  trash_thread", "rawInput": {"id": "t1"}}
    task = asyncio.create_task(hub.on_permission("s", write, opts))
    await asyncio.sleep(0.05)
    aid, card = next(iter(hub.approvals.items()))
    assert card["rule"] == "mcp:claude.ai Gmail:trash_thread"
    await hub.resolve_approval(aid, "allow_always")
    assert await task == "allow_once"          # Claude Code gets a one-off answer; Milo keeps the rule
    assert hub.permissions.rule("mcp:claude.ai Gmail:trash_thread") == "allow"
    assert await hub.on_permission("s", write, opts) == "allow_once" and hub.approvals == {}

    send = {"title": "mcp: milo-google  send gmail message", "rawInput": {"to": "x@y.z"}}
    for _ in range(2):                          # sending email asks every time, with no "Always allow"
        task = asyncio.create_task(hub.on_permission("s", send, opts))
        await asyncio.sleep(0.05)
        aid, card = next(iter(hub.approvals.items()))
        assert "allow_always" not in card["options"]
        await hub.resolve_approval(aid, "allow_once")
        assert await task == "allow_once"


def test_permissions_api(client):
    p = client.get("/api/permissions").json()
    assert p["auto_read"] is True and "smart_approve" in p["modes"]
    key = "mcp:claude.ai Gmail:send_message"
    rows = client.put("/api/permissions/rules", json={"key": key, "rule": "deny"}).json()["rules"]
    assert any(r["key"] == key and r["rule"] == "deny" for r in rows)
    assert client.put("/api/permissions/rules", json={"key": key, "rule": "nope"}).status_code == 400
    assert client.put("/api/permissions", json={"auto_read": False}).json()["auto_read"] is False
    client.put("/api/permissions", json={"auto_read": True})
    assert all(r["rule"] == "ask" for r in client.delete("/api/permissions/rules").json()["rules"])


def test_google_setup_validation(client):
    st = client.get("/api/google").json()
    assert st["configured"] is False and st["accounts"] == []
    assert client.put("/api/google/client", json={"client_id": "nope", "client_secret": "x"}).status_code == 400
    assert client.post("/api/google/accounts", json={"email": "a@b.co"}).status_code == 409   # not set up yet
    assert client.delete("/api/google/accounts/a@b.co").status_code == 404


def test_google_list_shows_accounts_whose_token_google_revoked(client, srv, monkeypatch):
    """Bug (2026-10-24): every account showed "Connected" while Google had revoked its token, and Settings had no
    Sign in. The list now refreshes each saved token (cached) and reports a dead one as "expired"."""
    g = srv.hub.google
    monkeypatch.setattr(g, "client", lambda: ("id.apps.googleusercontent.com", "secret"))
    calls = []

    async def refresh(creds):
        calls.append(creds["refresh_token"])
        return creds["refresh_token"] == "good"
    monkeypatch.setattr(g, "refresh", refresh)
    monkeypatch.setattr(g, "checked", {})
    for email, token in (("work@x.com", "good"), ("home@y.com", "dead")):
        g.add(email)
        (g.creds_dir / f"{email}.json").write_text(json.dumps({"refresh_token": token, "token_uri": "https://t"}))
    try:
        rows = {a["email"]: a for a in client.get("/api/google").json()["accounts"]}
        assert (rows["work@x.com"]["status"], rows["work@x.com"]["connected"]) == ("connected", True)
        assert (rows["home@y.com"]["status"], rows["home@y.com"]["connected"]) == ("expired", False)
        client.get("/api/google")
        assert sorted(calls) == ["dead", "good"]                 # the second list comes from the cache
    finally:
        for email in ("work@x.com", "home@y.com"):
            g.remove(email)


def test_google_sign_in_waits_for_a_new_token(srv, monkeypatch, tmp_path):
    """Sign in for an account with a dead token: its old file must not count as signed in."""
    g = srv.hub.google
    monkeypatch.setattr(g, "creds_dir", tmp_path)
    f = tmp_path / "home@y.com.json"
    f.write_text("{}")
    sent = []

    async def broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(srv.hub, "broadcast", broadcast)

    async def run():
        task = asyncio.create_task(srv.watch_google_sign_in("home@y.com", "r", f.stat().st_mtime))
        await asyncio.sleep(1.2)
        assert not sent                                          # still the dead token
        os.utime(f, (time.time() + 5, time.time() + 5))         # workspace-mcp saved the new one
        await asyncio.wait_for(task, 3)
    asyncio.run(run())
    assert {"t": "google"} in sent


def test_google_server_only_offered_when_configured(srv):
    servers, _ = srv.hub.mcp_servers()
    assert [s["name"] for s in servers] == ["milo-browser", "milo-weather"]


def test_weather_server_is_always_offered(srv):
    servers, key = srv.hub.mcp_servers()
    wx = servers[-1]
    assert wx["name"] == "milo-weather" and wx["url"].endswith(f"/mcp/weather?k={key}")
    assert wx["headers"][0]["value"] == f"Bearer {srv.CFG['browser_key']}"
    anon = TestClient(srv.app)
    assert anon.post("/mcp/weather", json={}).status_code == 401


def test_weather_result_becomes_a_card_on_its_step(srv, monkeypatch):
    """get_weather's data goes on its step (the app shows the card), whichever of the two comes first."""
    hub, sent = srv.hub, []

    async def record(ev):
        sent.append(ev)
    monkeypatch.setattr(hub, "broadcast", record)
    conv = srv.Conversation("wx-conv", "Weather")
    hub.convs[conv.id] = conv
    _, key = hub.mcp_servers()
    hub.mcp_keys[key] = conv.id
    data = {"location": "Portland, OR", "now": {"temp": 50}}
    title = "mcp: milo-weather  get weather"

    asyncio.run(hub.on_weather(key, {"location": "Portland, OR"}, data))
    assert sent == [] and conv.messages == []                                       # not running: nothing to show it on

    conv.running = True                                                             # the step first, then the result
    asyncio.run(hub._tool_event(conv, {"toolCallId": "t1", "title": title, "status": "pending",
                                       "rawInput": {"location": "Portland, OR"}}))
    asyncio.run(hub.on_weather(key, {"location": "Portland, OR"}, data))
    asyncio.run(hub._tool_event(conv, {"toolCallId": "t1", "status": "completed",
                                       "content": [{"content": {"type": "text", "text": '{"location":"Portland, OR"}'}}]}))
    [step] = conv.messages[-1]["tools"]
    assert step == {"id": "t1", "title": "Weather", "status": "completed", "detail": "Portland, OR", "at": 0,
                    "weather": data}                                                # the place, not the JSON
    assert sent[1] == {"t": "tool", "id": conv.id, "tool": step}

    conv.messages[-1]["tools"], sent[:] = [], []                                    # the result first
    asyncio.run(hub.on_weather(key, {"location": "Paris"}, data | {"location": "Paris, France"}))
    [early] = conv.messages[-1]["tools"]
    assert early["id"].startswith("wx-") and early["detail"] == "Paris, France" and sent[-1]["tool"] is early
    asyncio.run(hub._tool_event(conv, {"toolCallId": "t2", "title": title, "rawInput": {"location": "Paris"}}))
    [step] = conv.messages[-1]["tools"]
    assert step["id"] == "t2" and step["weather"]["location"] == "Paris, France"   # one step, not two
    assert sent[-1]["replaces"] == early["id"] and sent[-1]["tool"] is step
    hub.convs.pop(conv.id), hub.mcp_keys.pop(key)


def test_app_files_revalidate_and_carry_version(client, srv):
    v = srv.web_version()
    assert f'<meta name="milo-version" content="{v}">' in client.get("/").text
    for path in ("/", "/app.js", "/style.css", "/sw.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        assert ws.receive_json() == {"t": "hello", "version": v}


def test_web_version_changes_with_files(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "WEB", tmp_path)
    (tmp_path / "app.js").write_text("a")
    v1 = srv.web_version()
    assert srv.web_version() == v1
    (tmp_path / "app.js").write_text("ab")
    v2 = srv.web_version()
    (tmp_path / "new.css").write_text("")
    assert len({v1, v2, srv.web_version()}) == 3


def test_natural_voice_speaks_in_parts(client, srv):
    if not srv.hub.neural.available:
        pytest.skip("no Kokoro model")
    voices = client.get("/api/voices").json()
    assert voices[0]["natural"] and voices[0]["male"]
    assert any(v["name"] == "am_michael" for v in voices) and any(v["label"].endswith("(Mac)") for v in voices)
    assert srv.CFG["voice"] == "am_michael"
    parts = client.post("/api/tts", json={"text": "**Done.** I booked it for *three*. See you then!", "parts": True}).json()["parts"]
    assert parts == ["Done. I booked it for three. See you then!"]
    r = client.post("/api/tts", json={"text": parts[0], "raw": True})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4" and r.content[4:8] == b"ftyp"


def test_upload_saves_to_library_without_overwriting(client, srv):
    r1 = client.post("/api/upload", files={"file": ("../../evil name?.txt", b"one")}).json()
    r2 = client.post("/api/upload", files={"file": ("../../evil name?.txt", b"two")}).json()
    assert r1["path"] == "Uploads/evil name_.txt" and r2["path"] == "Uploads/evil name_-1.txt"
    assert open(r1["abs"], "rb").read() == b"one" and r2["abs"].startswith(str(srv.hub.library.root))
    assert any(i["path"] == r1["path"] for i in client.get("/api/library").json())
    assert client.post("/api/upload", files={"file": ("x.txt", b"")}).status_code == 400
    from fastapi.testclient import TestClient
    assert TestClient(srv.app).post("/api/upload", files={"file": ("x.txt", b"x")}).status_code == 401


def test_main_chat_is_made_once_and_cannot_be_deleted(client, srv):
    from server import Conversation
    assert client.get("/api/state").json()["mainId"] is None

    async def fake_new(source="app", title=None):
        conv = Conversation(f"s{len(srv.hub.convs)}", source=source, title=title or "New conversation", fixed_title=bool(title))
        srv.hub.convs[conv.id] = conv
        return conv
    srv.hub.new_conversation, old = fake_new, srv.hub.new_conversation
    try:
        main = asyncio.run(srv.hub.main_conv())
        again = asyncio.run(srv.hub.main_conv())
    finally:
        srv.hub.new_conversation = old
    st = client.get("/api/state").json()
    assert main is again and main.title == "Main chat" and st["mainId"] == main.id
    assert next(c for c in st["conversations"] if c["id"] == main.id)["main"] is True
    assert client.delete(f"/api/conversations/{main.id}").status_code == 400
    assert srv.Conversation(**main.to_json()).main                     # survives a restart
    srv.hub.convs.pop(main.id)


async def test_stop_takes_back_the_approval_card(srv, monkeypatch):
    """Stop (or deleting the chat) answers a waiting card: the app must hear it, or the card and its count stay."""
    hub, events = srv.hub, []

    async def record(ev):
        events.append(ev)
    monkeypatch.setattr(hub, "broadcast", record)
    task = asyncio.create_task(hub.request_approval("stop-chat", "Run rm?", "rm x", ["allow_once", "reject_once"]))
    await asyncio.sleep(0.05)
    aid = next(iter(hub.approvals))
    await hub.drop_approvals("stop-chat")
    assert await task is None and hub.approvals == {}
    assert {"t": "approval_done", "id": aid, "conv": "stop-chat", "decision": "cancelled"} in events


async def test_a_chat_deleted_while_it_runs_stays_deleted(srv, monkeypatch):
    """The turn that ends after the delete must not send the chat to the app again."""
    hub, events, go = srv.hub, [], asyncio.Event()

    async def nothing(*a, **k):
        pass

    async def record(ev):
        events.append(ev)

    async def prompt(sid, blocks):
        await go.wait()
        return {"stopReason": "cancelled"}
    for name, fn in [("ensure_running", nothing), ("prompt", prompt), ("cancel", nothing)]:
        monkeypatch.setattr(hub.goose, name, fn)
    monkeypatch.setattr(hub.goose, "is_loaded", lambda sid: True)
    monkeypatch.setattr(hub, "broadcast", record)
    monkeypatch.setattr(hub, "notify", nothing)
    conv = srv.Conversation("del-run")
    hub.convs[conv.id] = conv
    conv.running = True
    run = asyncio.create_task(hub._run(conv, "hi", False))
    await asyncio.sleep(0.05)
    await hub.cancel(conv)   # what DELETE /api/conversations/<id> does
    hub.convs.pop(conv.id)
    events.clear()
    go.set()
    await run
    assert not any(e["t"] == "conv" and e["conv"]["id"] == conv.id for e in events)
    assert "del-run" not in {c["id"] for c in hub.store.data}


def test_second_message_before_bound_goes_to_the_same_chat(client, srv, monkeypatch):
    """A new chat takes goose seconds to make: a message sent meanwhile carries the first one's ref."""
    made, sent = [], []

    async def fake_new(source="app", title=None, schedule=None):
        conv = srv.Conversation(f"ref-{len(made)}")
        srv.hub.convs[conv.id] = conv
        made.append(conv.id)
        return conv

    async def fake_submit(conv, text, voice, **k):
        sent.append((conv.id, text))
    monkeypatch.setattr(srv.hub, "new_conversation", fake_new)
    monkeypatch.setattr(srv.hub, "submit", fake_submit)
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.receive_json()   # hello
        ws.send_json({"type": "prompt", "id": None, "text": "first", "ref": "r1"})
        ws.send_json({"type": "prompt", "id": None, "text": "second", "ref": "r1"})
        bound = [ws.receive_json(), ws.receive_json()]
    assert made == ["ref-0"] and sent == [("ref-0", "first"), ("ref-0", "second")]
    assert all(b == {"t": "bound", "ref": "r1", "id": "ref-0"} for b in bound)
    srv.hub.convs.pop("ref-0")


def test_rename_chat(client, srv):
    from server import Conversation
    conv = Conversation("r1", title="Chat about stuff")
    srv.hub.convs[conv.id] = conv
    try:
        r = client.patch("/api/conversations/r1", json={"title": "  Trip   to Lisbon "})
        assert r.status_code == 200 and r.json()["title"] == "Trip to Lisbon"
        assert conv.title == "Trip to Lisbon" and conv.fixed_title          # goose won't rename it again
        assert client.patch("/api/conversations/r1", json={"title": " "}).status_code == 400
        assert client.patch("/api/conversations/nope", json={"title": "x"}).status_code == 404
    finally:
        srv.hub.convs.pop("r1")


def test_goals_api(client):
    g = client.post("/api/goals", json={"title": "Read 12 books", "section": "goal"}).json()
    assert client.post("/api/goals", json={"title": " "}).status_code == 400
    assert client.patch(f"/api/goals/{g['id']}", json={"done": True, "note": "8 so far"}).json()["done"] is True
    assert any(x["id"] == g["id"] and x["note"] == "8 so far" for x in client.get("/api/goals").json())
    assert client.patch("/api/goals/g-nope", json={"done": True}).status_code == 404
    assert client.patch(f"/api/goals/{g['id']}", json={"title": "   "}).status_code == 400   # an edit can't blank it
    assert client.patch(f"/api/goals/{g['id']}", json={"title": " Read\n12  books "}).json()["title"] == "Read 12 books"
    client.delete(f"/api/goals/{g['id']}")
    assert all(x["id"] != g["id"] for x in client.get("/api/goals").json())


def test_milo_goal_tags_update_goals(srv):
    g = srv.hub.goals.add("Learn Spanish")
    note = srv.hub.apply_goal({"id": g["id"], "done": True, "note": "B1 passed"}, None)
    assert note == {"kind": "goal", "text": "Goal reached: Learn Spanish"} and srv.hub.goals.get(g["id"])["done"]
    added = srv.hub.apply_goal({"title": "Watch the permit case", "section": "tracking", "note": ""}, None)
    assert added["text"] == "Tracking: Watch the permit case"
    assert srv.hub.apply_goal({"id": "g-missing", "note": "x"}, None) is None
    for x in list(srv.hub.goals.list()):
        srv.hub.goals.delete(x["id"])


def test_ideas_api_refreshes_when_old(client, srv, monkeypatch):
    calls = []
    monkeypatch.setattr(srv.hub, "refresh_ideas", lambda: calls.append(1))
    srv.hub.ideas.store.data = {"generated": 0, "items": []}
    client.get("/api/ideas")
    assert calls == [1]                                                     # never made: make them
    srv.hub.ideas.replace([{"id": "i-1", "title": "I can x", "detail": "", "prompt": "do x", "emoji": "✨"}])
    r = client.get("/api/ideas").json()
    assert calls == [1] and r["items"][0]["id"] == "i-1"                    # fresh: no new run
    client.post("/api/ideas/i-1/dismiss")
    assert client.get("/api/ideas").json()["items"] == []


def test_feed_api(client, srv, monkeypatch):
    from test_feed import post
    calls = []
    monkeypatch.setattr(srv.hub, "refresh_feed", lambda: calls.append(1))
    srv.hub.feed.store.data = {"settings": {}, "status": {}, "tabs": {}, "generated": 0}
    r = client.get("/api/feed").json()
    assert calls == [1] and r["status"]["state"] == "new" and r["tabs"] == {}     # never read: read now
    srv.hub.feed.save_tab("foryou", 50, {"brief": [{"text": "News", "posts": ["1"], "media": None}], "top": []}, [post("1")])
    srv.hub.feed.set_status("ok")
    r = client.get("/api/feed").json()
    assert calls == [1] and r["tabs"]["foryou"]["read"] == 50 and "1" in r["tabs"]["foryou"]["posts"]
    assert client.post("/api/feed/refresh").json() == {"busy": True} and calls == [1, 1]
    assert client.put("/api/feed/settings", json={"top": 4}).status_code == 400
    assert client.put("/api/feed/settings", json={"top": 3, "following": False}).json()["top"] == 3
    assert client.post("/api/feed/feedback", json={"post": "1", "kind": "mute"}).status_code == 200
    assert client.get("/api/feed").json()["settings"]["muted"] == ["lab"]
    assert client.post("/api/feed/feedback", json={"post": "nope", "kind": "mute"}).status_code == 404
    assert client.post("/api/feed/feedback", json={"post": "1", "kind": "like"}).status_code == 400
    assert client.post("/api/feed/vote", json={"post": "1", "vote": "like", "tab": "foryou"}).status_code == 200
    assert client.get("/api/feed").json()["votes"] == {"1": "like"}
    assert client.post("/api/feed/vote", json={"post": "1", "vote": ""}).status_code == 200
    assert client.get("/api/feed").json()["votes"] == {}
    assert client.post("/api/feed/vote", json={"post": "nope", "vote": "like"}).status_code == 404
    assert client.post("/api/feed/vote", json={"post": "1", "vote": "love"}).status_code == 400


def test_feed_media_only_from_x_and_fetched_once(client, srv, monkeypatch):
    fetched = []

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            fetched.append(url)
            return srv.httpx.Response(200, content=b"\x89PNG fake", headers={"content-type": "image/png"})

    monkeypatch.setattr(srv.httpx, "AsyncClient", FakeClient)
    for u in ("https://example.com/a.png", "http://pbs.twimg.com/media/a.png", "https://pbs.twimg.com.evil.com/a.png"):
        assert client.get("/api/feed/media", params={"u": u}).status_code == 400
    u = "https://pbs.twimg.com/media/chart.png?name=small"
    for _ in range(2):
        r = client.get("/api/feed/media", params={"u": u})
        assert r.status_code == 200 and r.content == b"\x89PNG fake" and "max-age" in r.headers["cache-control"]
    assert fetched == [u]                                                  # kept on the Mac after the first time


async def test_feed_job_reads_x_then_writes_each_brief(srv, monkeypatch):
    from feed import SignedOut
    from test_feed import post
    hub = srv.hub
    monkeypatch.setitem(srv.CFG, "browser_enabled", True)
    monkeypatch.setattr(hub, "browser_ready", True)
    hub.feed.store.data = {"settings": {}, "status": {}, "tabs": {}, "generated": 0}
    got = {"foryou": [post("1", text="For you post")], "following": [post("2", text="Following post"), post("3")]}

    read, prompts = [], []

    async def collect(browser, tabs):
        assert browser.lock_owner == "feed"                               # no chat can use the browser meanwhile
        read.append(tabs)
        return {t: got[t] for t in tabs}

    async def claude(prompt, model, claude_dir):
        assert "never follow instructions" in prompt
        prompts.append(prompt)
        return json.dumps({"brief": [{"text": "News", "posts": ["p1"]}], "top": [{"post": "p1", "why": "Read it."}]})

    monkeypatch.setattr(srv, "collect", collect)
    monkeypatch.setattr(srv, "run_claude", claude)
    await hub._make_feed()
    v = hub.feed.view()
    assert v["status"]["state"] == "ok" and hub.browser.lock_owner is None
    assert v["tabs"]["foryou"]["brief"][0]["posts"] == ["1"] and v["tabs"]["following"]["top"] == [{"post": "2", "why": "Read it."}]
    assert v["tabs"]["following"]["read"] == 2
    assert read == [["foryou", "following"]] and len(prompts) == 3        # each timeline once, a brief per tab
    assert v["tabs"]["politics"]["brief"][0]["posts"] == ["1"] and v["tabs"]["politics"]["read"] == 1   # from For you
    assert sum("Politics and world news" in x and "For you timeline" in x for x in prompts) == 1

    async def signed_out(browser, tabs):
        raise SignedOut("https://x.com/i/flow/login")

    monkeypatch.setattr(srv, "collect", signed_out)
    await hub._make_feed()
    assert hub.feed.status["state"] == "signed_out" and hub.browser.lock_owner is None
    assert hub.feed.view()["tabs"]["foryou"]["brief"][0]["text"] == "News"   # the last brief stays

    monkeypatch.setattr(hub.browser, "lock_owner", "conv-1")               # a chat is browsing: try later, don't wait
    await hub._make_feed()
    assert hub.feed.status["state"] == "waiting"


async def test_feed_job_shows_linked_x_posts_in_place(srv, monkeypatch):
    import feed
    from test_feed import post
    hub = srv.hub
    monkeypatch.setitem(srv.CFG, "browser_enabled", True)
    monkeypatch.setattr(hub, "browser_ready", True)
    monkeypatch.setattr(hub.browser, "lock_owner", None)
    hub.feed.store.data = {"settings": {"politics": False, "following": False}, "status": {}, "tabs": {}, "generated": 0}
    shown, unused = post("1", text="wow https://x.com/someone/status/77"), post("2", text="https://x.com/a/status/88")
    shown["xpost"], unused["xpost"] = "77", "88"
    fetched = []

    async def collect(browser, tabs):
        return {"foryou": [shown, unused]}

    async def claude(prompt, model, claude_dir):
        return json.dumps({"brief": [], "top": [{"post": "p1", "why": ""}]})

    async def fetch_post(client, tid):
        fetched.append(tid)
        return {"id": tid, "name": "Some One", "handle": "someone", "avatar": "", "text": "the post", "media": []}

    monkeypatch.setattr(srv, "collect", collect)
    monkeypatch.setattr(srv, "run_claude", claude)
    monkeypatch.setattr(feed, "fetch_post", fetch_post)
    await hub._make_feed()
    saved = hub.feed.view()["tabs"]["foryou"]["posts"]["1"]
    assert fetched == ["77"]                                               # only posts the feed shows
    assert saved["quote"]["text"] == "the post" and saved["text"] == "wow"


async def test_no_push_while_the_app_is_open(srv, monkeypatch):
    hub, sent = srv.hub, []

    async def push(title, body, url="/", tag=None, chat=None):
        sent.append(title)

    monkeypatch.setattr(hub.push, "send", push)
    monkeypatch.setattr(hub, "sockets", {"phone": True})
    monkeypatch.setattr(hub, "heard", {"phone": time.time()})
    await hub.notify("Needs your OK", "Buy it?", tag="a-1")                 # approvals and task results too
    assert sent == []
    hub.sockets["phone"] = False                                            # app in the background
    await hub.notify("Needs your OK", "Buy it?", tag="a-1")
    hub.sockets["phone"], hub.heard["phone"] = True, time.time() - 120     # gone without closing its socket
    await hub.notify("Due today", "2 due")
    assert sent == ["Needs your OK", "Due today"]


async def test_long_push_goes_out_as_a_few_words(srv, monkeypatch):
    hub, sent, prompts = srv.hub, [], []

    async def push(title, body, url="/", tag=None, chat=None):
        sent.append((title, body, url))

    async def claude(prompt, model, claude_dir, timeout=420):
        prompts.append((prompt, model))
        return '"Booked the Lisbon flight for Friday."\n'

    monkeypatch.setattr(hub.push, "send", push)
    monkeypatch.setattr(hub.push.subs, "data", [{"endpoint": "https://push.example/1"}])
    monkeypatch.setattr(hub, "sockets", {})
    monkeypatch.setattr(srv, "run_claude", claude)
    monkeypatch.setitem(hub.convs, "c-1", srv.Conversation("c-1", title="Lisbon trip"))
    await hub.notify("Due today", "2 due")                                     # short: as it is, no model call
    long = "I looked at every flight to Lisbon this week and compared the prices. " * 5
    await hub.notify("Lisbon trip", long, "c-1")
    await asyncio.gather(*hub.notices)                                         # the caller did not wait for the model
    assert sent == [("Due today", "2 due", "/"), ("Lisbon trip", "Booked the Lisbon flight for Friday", "/#c=c-1")]
    assert len(prompts) == 1 and prompts[0][1] == srv.CFG["notice_model"] and "compared the prices" in prompts[0][0]

    async def broken(prompt, model, claude_dir, timeout=420):
        raise RuntimeError("You've hit your session limit")

    monkeypatch.setattr(srv, "run_claude", broken)                             # no model: the start of the text
    await hub.notify("Lisbon trip", long, "c-1")
    await asyncio.gather(*hub.notices)
    assert sent[-1][1].startswith("I looked at every flight") and len(sent[-1][1]) <= 120



async def test_push_opens_the_chat_it_is_about(srv, monkeypatch):
    """Every alert carries the id of its chat: a reply that finished (also in a compacted or cleared chat, which has a
    new session), an approval named by its session, a task result. A chat's own id wins over a session with that name."""
    hub, sent = srv.hub, []

    async def push(title, body, url="/", tag=None, chat=None):
        sent.append((title, url))

    monkeypatch.setattr(hub.push, "send", push)
    monkeypatch.setattr(hub, "sockets", {})
    slides = srv.Conversation("20261020_8", title="Paper slides", sid="20261020_25")   # compacted: a new session
    main = srv.Conversation("20261017_4", title="Main chat", main=True, sid="20261020_8")   # a session named like a chat
    for c in (slides, main):
        monkeypatch.setitem(hub.convs, c.id, c)
    await hub.notify("Paper slides", "Ready.", slides.id)                       # the reply that made the deck
    await hub.notify("Needs your OK", "Run it?", "20261020_25", tag="a-1")      # named by the chat's session
    await hub.notify("Main chat", "Done.", main.id)
    await hub.notify("Gone", "Done.", "no-such-chat")                           # no chat: the app's start
    assert sent == [("Paper slides", "/#c=20261020_8"), ("Needs your OK", "/#c=20261020_8"),
                    ("Main chat", "/#c=20261017_4"), ("Gone", "/")]


async def test_milo_reacts_now_and_then_with_the_cheap_model(srv, monkeypatch):
    hub, sent, prompts = srv.hub, [], []
    conv = srv.Conversation("c-react", title="Exam")
    hub.convs[conv.id] = conv

    async def claude(prompt, model, claude_dir, timeout=420):
        prompts.append((prompt, model))
        return "\U0001F389"

    async def broadcast(ev):
        sent.append(ev)

    def say(text):
        msg = {"role": "user", "text": text, "ts": time.time()}
        conv.messages.append(msg)
        hub.maybe_react(conv, msg)
        return msg

    monkeypatch.setattr(srv, "run_claude", claude)
    monkeypatch.setattr(hub, "broadcast", broadcast)
    monkeypatch.setattr(hub, "someone_looking", lambda: True)
    monkeypatch.setattr(srv.random, "random", lambda: 0.3)
    plain = say("Move the report to Downloads")                                 # no feeling: a 10% chance, missed
    assert not hub.side_tasks
    good = say("I passed the exam!")
    await asyncio.gather(*hub.side_tasks)
    assert good["reaction"] == "\U0001F389" and "reaction" not in plain
    assert sent == [{"t": "reaction", "id": "c-react", "ts": good["ts"], "emoji": "\U0001F389"}]
    assert len(prompts) == 1 and prompts[0][1] == srv.CFG["reaction_model"] and "passed the exam" in prompts[0][0]
    say("Thanks so much!")                                                      # right after a reaction: no call
    monkeypatch.setattr(hub, "someone_looking", lambda: False)                  # Siri: nobody sees bubbles
    for _ in range(srv.REACT_EVERY):
        say("Wow, thanks!")
    assert not hub.side_tasks and len(prompts) == 1
    hub.convs.pop(conv.id)


async def test_milo_reacts_when_asked(srv, monkeypatch):
    hub, sent = srv.hub, []
    conv = srv.Conversation("c-asked", title="Chat")
    hub.convs[conv.id] = conv

    async def broadcast(ev):
        sent.append(ev)

    monkeypatch.setattr(hub, "broadcast", broadcast)
    conv.messages += [{"role": "user", "text": "Love you", "ts": 1.0}, {"role": "assistant", "text": "Love you too.", "tools": [], "notes": []},
                      {"role": "user", "text": "React to my message?", "ts": 2.0},
                      {"role": "assistant", "text": 'Done. <react back="1">\u2764\ufe0f</react>', "tools": [], "notes": []}]
    await hub._finish(conv, "end_turn", None, False)
    assert conv.messages[0]["reaction"] == "\u2764\ufe0f" and "reaction" not in conv.messages[2]
    assert conv.messages[-1]["text"] == "Done." and {"t": "reaction", "id": "c-asked", "ts": 1.0, "emoji": "\u2764\ufe0f"} in sent
    hub.convs.pop(conv.id)

@pytest.mark.skipif(not shutil.which("qlmanage") or not shutil.which("textutil"), reason="macOS Quick Look")
def test_library_preview_through_quick_look(client, srv):
    lib = srv.hub.library.root
    (lib / "notes.txt").write_text("Quarterly plan for the lab")
    subprocess.run(["textutil", "-convert", "docx", "-output", str(lib / "plan.docx"), str(lib / "notes.txt")], check=True)
    r = client.get("/api/library/preview", params={"path": "plan.docx"}).json()
    assert r["type"] == "text/html" and re.fullmatch(r"/preview/[0-9a-f]{32}/Preview\.html", r["url"])
    assert client.get("/api/library/preview", params={"path": "plan.docx"}).json() == r     # made once per version
    page = TestClient(srv.app).get(r["url"])                                  # no token: the key in the URL is the check
    assert page.status_code == 200 and "Quarterly plan for the lab" in page.text and "gesturestart" in page.text
    assert "sandbox allow-scripts" in page.headers["content-security-policy"]
    key = r["url"].split("/")[2]
    for bad in (f"/preview/{'0' * 32}/Preview.html", f"/preview/{key}/..%2F..%2Fconfig.json", f"/preview/{key}/.hidden", "/preview/x/Preview.html"):
        assert TestClient(srv.app).get(bad).status_code == 404, bad
    (lib / "plan.docx").write_bytes((lib / "plan.docx").read_bytes() + b"\0")   # a new version gets a new preview
    assert client.get("/api/library/preview", params={"path": "plan.docx"}).json()["url"] != r["url"]
    assert client.get("/api/library/preview", params={"path": "nope.docx"}).status_code == 404


def test_library_pages_never_run_scripts_as_the_app(client, srv):
    lib = srv.hub.library.root
    (lib / "page.html").write_text("<script>alert(localStorage.token)</script>")
    (lib / "plain.txt").write_text("hi")
    assert client.get("/api/library/file", params={"path": "page.html"}).headers["content-security-policy"] == "sandbox"
    assert "content-security-policy" not in client.get("/api/library/file", params={"path": "plain.txt"}).headers


def test_a_reply_stays_whole_when_a_message_waits(srv):
    """A message queued while Milo replies waits below the reply; the rest of the reply goes on above it. The next turn
    gets a reply of its own."""
    conv = srv.Conversation("q-test", messages=[{"role": "user", "text": "one", "ts": 1}])
    reply = srv.Hub._assistant_msg(conv)
    reply["text"] += "a "
    conv.messages.append({"role": "user", "text": "two", "ts": 2, "queued": True})
    assert srv.Hub._assistant_msg(conv) is reply
    conv.messages.append({"role": "user", "text": "three", "ts": 4, "queued": True})
    assert [m["text"] for m in conv.messages] == ["one", "a ", "two", "three"]
    del conv.messages[2]["queued"]   # the next turn: "two" runs
    nxt = srv.Hub._assistant_msg(conv)
    assert nxt is not reply and conv.messages.index(nxt) == 3   # above "three", which still waits


def test_milo_restarts_the_bridge_after_its_reply(srv, monkeypatch):
    """Milo runs inside the bridge, so <restart/> restarts it once the reply is done: a detached helper starts a new
    bridge and this one stops itself. A scheduled run can't restart it."""
    hub, started, signals = srv.hub, [], []
    monkeypatch.setattr(srv.subprocess, "Popen", lambda args, **k: started.append((args, k)))
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    fake_goose(hub, monkeypatch, reply="Restarting now, back in about 20 seconds.<restart/>")

    async def turn(scheduled=False):
        conv = await hub.new_conversation()
        conv.messages.append({"role": "user", "text": "restart the server", "ts": time.time(), "scheduled": scheduled})
        conv.running = True
        await hub._run(conv, "restart the server", False)
        await asyncio.gather(*hub.side_tasks)
        return conv
    conv = asyncio.run(turn(scheduled=True))
    assert conv.messages[-1]["text"] == "Restarting now, back in about 20 seconds." and not started and not signals
    try:
        conv = asyncio.run(turn())
        assert conv.messages[-1]["text"] == "Restarting now, back in about 20 seconds."
        (args, kw), = started
        assert args[1:] == [str(srv.ROOT / "restart.py"), str(os.getpid())] and kw["start_new_session"]
        assert signals == [(os.getpid(), srv.signal.SIGTERM)]
    finally:
        hub.restarting = False


def test_claude_profile_gets_the_guard_hook(srv):
    """The hook runs in every permission mode ("Never ask" sends no command to on_permission)."""
    settings = json.loads((srv.CLAUDE_DIR / "settings.json").read_text())
    (match,) = [m for m in settings["hooks"]["PreToolUse"] if "guard.py" in m["hooks"][0]["command"]]
    assert match["matcher"] == "Bash"
    srv.install_guard()   # again: still one
    assert len(json.loads((srv.CLAUDE_DIR / "settings.json").read_text())["hooks"]["PreToolUse"]) == 1


def test_stop_interrupts_claude_and_the_next_turn_forks(srv, monkeypatch):
    """Bug (2026-10-20): after Stop, goose ended the turn but Claude Code under it ran a subagent on for minutes.
    Stop now interrupts Claude, and the next turn goes on in a fork of the session, so no history is lost.
    A Stop that ends subagents says so in a pop-up."""
    hub = srv.hub
    prompts = fake_goose(hub, monkeypatch)
    stopped, forked, found, toasts = [], [], iter([True, False]), []

    async def record(ev):
        if ev["t"] == "toast":
            toasts.append(ev["text"])
    monkeypatch.setattr(hub, "broadcast", record)

    async def interrupt(sid):
        stopped.append(sid)
        return next(found)

    async def fork_session(sid, servers):
        forked.append(sid)
        return sid + "-fork"
    monkeypatch.setattr(hub.goose, "interrupt", interrupt)
    monkeypatch.setattr(hub.goose, "fork_session", fork_session)

    async def turn(conv, text):
        conv.messages.append({"role": "user", "text": text, "ts": 0})
        await hub._run(conv, text, False)

    async def go():
        conv = await hub.new_conversation()
        first = conv.sid
        await turn(conv, "one")
        conv.messages[-1]["tools"] = [{"id": "t1", "title": "Task", "status": "pending"},   # a subagent at work
                                      {"id": "t2", "title": "Task", "status": "completed"}]
        conv.running = True
        await hub.cancel(conv)                      # Claude was stopped: the next turn needs a fork
        await turn(conv, "two")
        assert stopped == [first] and forked == [first]
        assert prompts[-1][0] == conv.sid == first + "-fork"
        assert toasts == ["Stopped Milo and 1 helper agent"]
        conv.running = True
        conv.messages.append({"role": "user", "text": "four", "ts": 0})
        await hub.cancel(conv)                      # no reply yet, so no agent; no Claude process: same session
        await hub._run(conv, "four", False)
        assert forked == [first] and prompts[-1][0] == first + "-fork"
        assert len(toasts) == 1                     # no agent was at work: no pop-up
        conv.messages[-1]["tools"] = [{"id": "t3", "title": "Task", "status": "in_progress"}] * 2
        conv.running = True
        stopped.clear()
        found = iter([False])
        monkeypatch.setattr(hub.goose, "interrupt", lambda sid: asyncio.sleep(0, next(found)))
        await hub.cancel(conv)
        await conv.halting
        assert toasts[-1] == "Couldn't stop 2 helper agents on your Mac"
    asyncio.run(go())


def test_a_stop_that_ends_agents_can_be_undone(srv, monkeypatch):
    """The user's Stop with helper agents at work waits a few seconds with Undo in a pop-up. Undo keeps everything
    running; otherwise the Stop goes through. A second Stop doesn't wait. A Stop without agents never waits."""
    hub = srv.hub
    events, stopped = [], []

    async def record(ev):
        events.append(ev)

    async def interrupt(sid):
        stopped.append(sid)
        return True

    async def nothing(*a, **k):
        pass
    monkeypatch.setattr(hub, "broadcast", record)
    monkeypatch.setattr(hub.goose, "cancel", nothing)
    monkeypatch.setattr(hub.goose, "interrupt", interrupt)
    monkeypatch.setattr(srv, "STOP_GRACE", 0.05)

    def chat(cid, agents):
        conv = srv.Conversation(cid)
        conv.messages = [{"role": "user", "text": "go", "ts": 0},
                         {"role": "assistant", "text": "", "ts": 0, "notes": [],
                          "tools": [{"id": "t", "title": "Task", "status": "in_progress"}] * agents}]
        conv.running = True
        hub.convs[cid] = conv
        return conv

    async def go():
        conv = chat("undo-1", 1)
        await hub.cancel(conv, grace=True)
        assert events[-1] == {"t": "stopping", "id": "undo-1", "agents": 1, "grace": 0.05}
        assert not conv.stopping and not stopped
        await hub.keep(conv)                                  # Undo
        assert events[-1] == {"t": "stop_undone", "id": "undo-1"}
        await asyncio.sleep(0.1)
        assert not conv.stopping and not stopped and not conv.halting

        await hub.cancel(conv, grace=True)                    # no Undo this time
        await asyncio.sleep(0.1)
        await conv.halting
        assert conv.stopping and stopped == ["undo-1"]
        assert events[-1] == {"t": "toast", "stop": True, "text": "Stopped Milo and 1 helper agent"}
        await hub.keep(conv)                                  # too late: nothing happens
        assert events[-1]["t"] == "toast"

        conv = chat("undo-2", 2)
        await hub.cancel(conv, grace=True)
        await hub.cancel(conv, grace=True)                    # a second Stop stops at once
        assert conv.stopping
        await conv.halting
        assert stopped[-1] == "undo-2"

        conv = chat("undo-3", 0)
        await hub.cancel(conv, grace=True)                    # no agents: no wait
        assert conv.stopping and not any(e["t"] == "stopping" and e["id"] == "undo-3" for e in events)
        for cid in ("undo-1", "undo-2", "undo-3"):
            hub.convs.pop(cid)
    asyncio.run(go())


def test_siri_gets_its_own_short_answer_hint(srv):
    """Live eval (2026-10-20): Siri answers ran 10 sentences. Siri got the app's voice hint, so Milo never knew the
    Shortcut reads the reply aloud. While a Shortcut waits for the turn, the prompt says so."""
    hub = srv.hub
    conv = srv.Conversation("siri-hint")
    conv.ctx = (hub.goose.proc.pid if hub.goose.proc else 0, hub.memory.version, hub.goals.version, hub.scheduler.version)
    app_voice = hub._prompt_blocks(conv, "what's next", True)[0]["text"]
    assert srv.VOICE_HINT in app_voice and srv.SIRI_HINT not in app_voice
    hub.siri_wait[conv.id] = None
    try:
        siri = hub._prompt_blocks(conv, "what's next", True)[0]["text"]
    finally:
        hub.siri_wait.pop(conv.id)
    assert srv.SIRI_HINT in siri and srv.VOICE_HINT not in siri
    assert srv.VOICE_HINT not in hub._prompt_blocks(conv, "typed", False)[0]["text"]


def test_siri_reads_the_say_part_and_points_to_the_chat_only_when_it_has_more(srv, monkeypatch):
    """Incident (2026-10-27): Siri said "the details are in the app", but the chat held the same short answer. The
    Shortcut now reads the <say> part, the chat keeps the whole reply, and the pointer comes only with real detail."""
    hub = srv.hub
    fake_goose(hub, monkeypatch)

    async def nothing(*a, **k):
        pass
    monkeypatch.setattr(hub, "notify", nothing)

    async def ask(text):
        conv = await hub.new_conversation(source="siri")
        conv.messages.append({"role": "user", "text": "How does my Wednesday look?", "voice": True, "ts": 0})
        conv.messages.append({"role": "assistant", "text": text, "tools": [], "notes": [], "ts": 0})
        waiter = asyncio.get_running_loop().create_future()
        hub.siri_wait[conv.id] = waiter
        await hub._finish(conv, "end_turn", None, True)
        hub.convs.pop(conv.id)
        return await waiter, conv.messages[-1]["text"]

    detail = ("<say>Class at 12:45 and VISTA writing from 3:30 to 6:30.</say>\n\n- 6:15 run\n- 7:45 ASTRA abstract\n"
              "- 12:45 Robotics class\n- 3:30 VISTA paper writing<suggest>Plan my VISTA work</suggest>")
    spoken, shown = asyncio.run(ask(detail))
    assert spoken == "Class at 12:45 and VISTA writing from 3:30 to 6:30. " + srv.SIRI_MORE
    assert shown.startswith("Class at 12:45") and "- 7:45 ASTRA abstract" in shown and "<say>" not in shown
    spoken, shown = asyncio.run(ask("<say>Nothing is planned for Wednesday.</say><suggest>Thanks</suggest>"))
    assert spoken == shown == "Nothing is planned for Wednesday."                  # no pointer to an empty chat
    spoken, _ = asyncio.run(ask("Class at 12:45."))                                # no tag: the whole answer
    assert spoken == "Class at 12:45."


def test_an_email_goes_out_only_after_send(srv):
    """Live eval (2026-10-20): Milo asked "Want me to send it?" and sent on "Yeah let's do that". The user's rule is a
    clear "send", so the bridge refuses a send until the user's last message says it."""
    hub = srv.hub
    conv = srv.Conversation("send-guard")
    hub.convs[conv.id], hub.mcp_keys["sg-key"] = conv, conv.id

    def says(text, **kw):
        conv.messages.append({"role": "user", "text": text, "ts": 0, **kw})
        return hub.google_guard("sg-key", "send_gmail_message", {})
    try:
        assert says("Reply to Sam and ask about the SSH keys")
        assert hub.google_guard("sg-key", "draft_gmail_message", {}) is None   # drafts are always fine
        assert says("Yeah let's do that")
        assert says("Looks good, send it.") is None
        assert says("Don't send it yet, I want to change a line")
        assert says("send", queued=True)                  # not the message this turn answers
        assert says("Check my email for anything urgent", scheduled=True) is None   # a recurring task's run
    finally:
        hub.convs.pop(conv.id)
        hub.mcp_keys.pop("sg-key")


def test_milo_reacts_only_when_asked(srv, monkeypatch):
    """Live eval (2026-10-20): Milo put a heart on "Love you" by itself. A <react> counts only when the user asked."""
    hub = srv.hub
    prompts = fake_goose(hub, monkeypatch, reply="Love you too. <react>❤️</react>")

    async def go(text):
        conv = await hub.new_conversation()
        conv.messages.append({"role": "user", "text": text, "ts": 1})
        await hub._run(conv, text, False)
        return conv.messages[0].get("reaction")
    assert asyncio.run(go("Love you")) is None
    assert asyncio.run(go("React to my message with a heart")) == "❤️"


def reacting_hub(srv, monkeypatch, cid, answers, roll):
    """A chat whose reaction calls answer from answers and whose dice roll roll(); returns (conv, say, prompts, sent)."""
    hub, sent, prompts = srv.hub, [], []
    conv = srv.Conversation(cid, title="Chat")
    hub.convs[conv.id] = conv

    async def claude(prompt, model, claude_dir, timeout=420):
        prompts.append(prompt)
        return answers.pop(0)

    async def broadcast(ev):
        sent.append(ev)

    async def say(text):
        msg = {"role": "user", "text": text, "ts": time.time()}
        conv.messages.append(msg)
        hub.maybe_react(conv, msg)
        await asyncio.gather(*hub.side_tasks)
        return msg

    monkeypatch.setattr(srv, "run_claude", claude)
    monkeypatch.setattr(hub, "broadcast", broadcast)
    monkeypatch.setattr(hub, "someone_looking", lambda: True)
    monkeypatch.setattr(srv.random, "random", roll)
    return conv, say, prompts, sent


async def test_a_none_reaction_does_not_hide_the_next_message(srv, monkeypatch):
    """2026-10-20: 1 reaction in 128 messages; "I love you" got none. A call that picked no emoji started the
    pause, so a plain message checked first hid the next REACT_EVERY - 1 messages."""
    conv, say, prompts, sent = reacting_hub(srv, monkeypatch, "c-none", ["none", "\u2764\ufe0f"], lambda: 0.05)
    try:
        plain = await say("Move the report to Downloads")          # checked (a 10% chance, hit): no emoji
        love = await say("I love you")                              # still gets its chance
        assert "reaction" not in plain and love["reaction"] == "\u2764\ufe0f" and len(prompts) == 2
        assert sent == [{"t": "reaction", "id": "c-none", "ts": love["ts"], "emoji": "\u2764\ufe0f"}]
        assert conv.since_react == 0 and not conv.reacting
        again = await say("Love you!")                               # right after a reaction: a pause, no call
        assert "reaction" not in again and len(prompts) == 2
    finally:
        srv.hub.convs.pop("c-none")


async def test_reactions_stay_occasional(srv, monkeypatch):
    """The user: "i don't want to be deterministic". A message with feeling gets a chance, not a sure reaction."""
    rolls = [0.95, 0.3]
    conv, say, prompts, sent = reacting_hub(srv, monkeypatch, "c-dice", ["\u2764\ufe0f"], lambda: rolls.pop(0))
    try:
        missed = await say("I love you")                             # the dice say no: no call, no emoji
        assert "reaction" not in missed and not prompts and not sent
        hit = await say("Love you so much")                          # the dice say yes: the model picks the emoji
        assert hit["reaction"] == "\u2764\ufe0f" and len(prompts) == 1 and "Love you so much" in prompts[0]
        assert srv.react_chance("Move the report to Downloads", srv.REACT_EVERY) < srv.react_chance("I love you", srv.REACT_EVERY) < 1
    finally:
        srv.hub.convs.pop("c-dice")


async def test_one_reaction_call_at_a_time(srv, monkeypatch):
    """Two quick messages make one call: the second waits for no answer, and a failed call frees the chat."""
    conv, say, prompts, sent = reacting_hub(srv, monkeypatch, "c-busy", [], lambda: 0.05)
    hub = srv.hub
    gate = asyncio.Event()

    async def slow(prompt, model, claude_dir, timeout=420):
        prompts.append(prompt)
        await gate.wait()
        raise RuntimeError("You've hit your session limit")
    monkeypatch.setattr(srv, "run_claude", slow)
    try:
        for text in ("Thanks!", "Thanks again!"):
            msg = {"role": "user", "text": text, "ts": time.time()}
            conv.messages.append(msg)
            hub.maybe_react(conv, msg)
            await asyncio.sleep(0)
        assert len(prompts) == 1 and conv.reacting
        gate.set()
        await asyncio.gather(*hub.side_tasks)
        assert not conv.reacting and not sent and conv.since_react == srv.REACT_EVERY + 1   # the failure starts no pause
    finally:
        hub.convs.pop("c-busy")


def test_quiet_inside_a_task_stays_in_its_text(srv, monkeypatch):
    """Bug (2026-10-20): the Email check task was saved as "If nothing important is new, add  to the reply": the
    reply's <quiet/> was taken out before its <schedule> tag was read, so the task's text lost it."""
    hub = srv.hub
    fake_goose(hub, monkeypatch)
    conv = asyncio.run(hub.new_conversation())
    text = ('Set it up.<schedule cron="0 6-22/2 * * *" kind="task" title="Mail check">Check mail. If nothing is new, '
            'add <quiet/> to the reply.</schedule><suggest>Thanks</suggest>')
    conv.messages.append({"role": "assistant", "text": text, "tools": [], "notes": [], "ts": 0})
    asyncio.run(hub._finish(conv, "end_turn", None, False))
    [task] = [s for s in hub.scheduler.store.data if s["title"] == "Mail check"]
    assert task["text"] == "Check mail. If nothing is new, add <quiet/> to the reply."
    assert conv.messages[-1]["text"] == "Set it up."
    hub.scheduler.remove(task["id"])


def test_tabs_close_only_when_milo_is_idle(srv, monkeypatch):
    """Hub.close_tabs leaves the tabs while a chat or the feed works, a task holds the browser or the user drives it."""
    from types import SimpleNamespace
    calls = []

    async def close_milos_tabs():
        calls.append(1)
        return 0
    fake = SimpleNamespace(browser=SimpleNamespace(is_connected=lambda: True), lock_owner=None, controller="milo",
                           working=lambda: False, close_milos_tabs=close_milos_tabs)
    monkeypatch.setattr(srv.hub, "browser", fake)
    for change in [{"working": lambda: True}, {"lock_owner": "c1"}, {"controller": "user"}, {}]:
        busy = SimpleNamespace(**{**vars(fake), **change})
        monkeypatch.setattr(srv.hub, "browser", busy)
        asyncio.run(srv.hub.close_tabs())
    assert calls == [1]   # only the idle one


def test_calendar_changes_need_the_users_ok(srv):
    """A calendar event (or a work block) changes only when the user's last message agrees or asks for it, never in a
    scheduled run, and RSVPs are not changes (BEHAVIOR #94: events were made from "plan my day" and a loose note)."""
    hub = srv.hub
    conv = srv.Conversation("cal-guard")
    hub.convs[conv.id], hub.mcp_keys["k-cal"] = conv, conv.id

    def says(text, tool="manage_event", scheduled=False, **args):
        conv.messages[:] = [{"role": "user", "text": text, "ts": 0, **({"scheduled": True} if scheduled else {})}]
        return hub.google_guard("k-cal", tool, {"action": "create", **args})
    try:
        for text in ("Plan my day tomorrow", "What do I have on Friday?", "I'm thinking about a run tonight",
                     "No, don't add it yet", "wait, don't put it on the calendar"):
            assert says(text) and "Not changed" in says(text), text
        for text in ("Yes, put them on the calendar.", "ok go ahead", "Move the VISTA block to Friday 2pm",
                     "sounds good", "delete the run event"):
            assert says(text) is None, text
        assert says("yes", tool="plan_block") is None and says("plan it", tool="plan_block")
        assert "scheduled task never changes the calendar" in says("Check my day", scheduled=True)
        assert says("Plan my day", action="rsvp") is None                        # answering an invite is not a change
        assert says("Plan my day", tool="get_events") is None                    # reads are never held
    finally:
        hub.convs.pop(conv.id), hub.mcp_keys.pop("k-cal")


def test_a_task_run_sees_the_main_chats_latest_messages(srv, monkeypatch):
    """A task works in its hidden chat: the main chat's messages of the last day come with its run, so it knows what
    was done, moved or dropped there today (BEHAVIOR #94: the briefing listed a task removed 7 minutes earlier)."""
    hub = srv.hub
    prompts = []

    async def no_run(conv, text, voice, task=False):
        prompts.append(text)

    async def new_session(servers):
        return f"tr-{len(hub.convs)}"
    monkeypatch.setattr(hub, "_run", no_run)
    monkeypatch.setattr(hub.goose, "new_session", new_session)

    async def go():
        main = await hub.main_conv()
        main.messages[:] = [{"role": "user", "text": "Remove the workshop review, it's not real", "ts": time.time() - 600},
                            {"role": "assistant", "text": "Removed it.", "ts": time.time() - 590},
                            {"role": "user", "text": "Old news from last week", "ts": time.time() - 8 * 86400}]
        task = hub.scheduler.add(title="Morning briefing", text="Brief me", cron="0 6 * * *")
        tconv = await hub.schedule_conversation(task)
        await hub.submit(tconv, "Brief me", False, scheduled=True)
        await hub.submit(main, "hello", False)
        hub.scheduler.remove(task["id"])
        hub.convs.pop(tconv.id), hub.convs.pop(main.id)
    asyncio.run(go())
    run, said = prompts
    assert "main chat" in run and "User: Remove the workshop review" in run and "You: Removed it." in run
    assert "Old news" not in run and said == "hello"                             # only the task run gets it


def test_every_message_goes_to_the_conversation_log(srv, monkeypatch):
    """The user's message and Milo's reply land in the day's file in the Conversations folder (BEHAVIOR #98)."""
    hub = srv.hub
    fake_goose(hub, monkeypatch, reply="Noted, see you tomorrow.")

    async def go():
        conv = await hub.new_conversation(title="Evening")
        await hub.submit(conv, "Logging off for today", False)
        await conv.done.wait()
        hub.convs.pop(conv.id)
    asyncio.run(go())
    assert hub.convlog.root == srv.Path(srv.CFG["library_dir"]).parent / "Conversations"
    text = hub.convlog.path(time.time()).read_text()
    assert 'You, in "Evening"\n\nLogging off for today\n' in text and 'Milo, in "Evening"\n\nNoted, see you tomorrow.\n' in text
