"""Every kind of alert names the chat a tap must open, through the real code paths (not hub.notify called by hand):
one-time and recurring tasks, side and Main chat replies (also after a compaction,
when the goose session is no longer the chat id), approvals asked by a session, and browser alerts.
goose, Whisper and Chrome are not started; Push.send is caught, so nothing leaves the Mac."""

import asyncio
import importlib
import json
import os
import uuid

import pytest

TOKEN = "test-token"


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    (data / "config.json").write_text(json.dumps({"token": TOKEN, "whisper_model": "/nonexistent",
                                                  "library_dir": str(data / "lib"), "browser_headless": True}))
    os.environ["MILO_DATA_DIR"] = str(data)
    os.environ["MILO_KEYCHAIN_SERVICE"] = f"Milo-notiftest-{uuid.uuid4().hex[:8]}"
    import server
    server = importlib.reload(server)
    yield server
    os.environ.pop("MILO_DATA_DIR"), os.environ.pop("MILO_KEYCHAIN_SERVICE")


@pytest.fixture
def pushes(srv, monkeypatch):
    """Pushes as (title, url, tag). No app window is open, so every alert goes out."""
    hub, sent = srv.hub, []

    async def send(title, body, url="/", tag=None, chat=None):
        sent.append((title, url, tag))

    async def nothing(*a, **k):
        pass

    ids = (f"2026102{n}_{i}" for n in range(9) for i in range(1, 999))   # goose-like session ids

    async def new_session(servers):
        return next(ids)

    monkeypatch.setattr(hub.push, "send", send)
    monkeypatch.setattr(hub, "sockets", {})
    monkeypatch.setattr(hub, "convs", {})
    monkeypatch.setattr(hub, "mcp_keys", {})
    monkeypatch.setattr(hub.goose, "new_session", new_session)
    monkeypatch.setattr(hub, "_run", nothing)
    yield sent
    for item in list(hub.scheduler.store.data):
        hub.scheduler.remove(item["id"])


def reply(srv, conv, text="Done."):
    """Milo answers the turn that is waiting in conv, as goose would, and the turn ends."""
    conv.messages.append({"role": "assistant", "text": text, "notes": [], "ts": 1, "tools": []})

    async def finish():   # a task's message goes to the main chat in the background
        await srv.hub._finish(conv, "end_turn", None, False)
        await asyncio.gather(*srv.hub.side_tasks)
    asyncio.run(finish())
    conv.running = False


def test_one_time_task_result_opens_the_main_chat(srv, pushes):
    """A task works in its hidden chat; its message, and so the alert's tap, is in the main chat."""
    hub = srv.hub
    item = hub.scheduler.add(title="Overnight prep", text="Prepare the slides", when="2099-01-01T02:00")
    asyncio.run(hub.fire_schedule(item))
    conv = next(c for c in hub.convs.values() if c.title == "Overnight prep")
    assert conv.schedule == item["id"]                    # one time too: a hidden task chat, not a side chat
    reply(srv, conv, "The slides are ready.")
    assert pushes == [("Overnight prep", f"/#c={hub.main_id()}", None)]


def test_recurring_task_result_opens_the_main_chat_after_a_new_session_per_run(srv, pushes):
    """Each run of a recurring task moves its hidden chat to a new goose session: the alert still opens the main chat."""
    hub = srv.hub
    item = hub.scheduler.add(title="Email check", text="Check email", cron="0 6-22/2 * * *")
    asyncio.run(hub.fire_schedule(item))
    conv = next(c for c in hub.convs.values() if c.schedule == item["id"])
    reply(srv, conv, "Two new emails.")
    asyncio.run(hub._new_session(conv))                 # what _run does at the start of the second run
    assert conv.sid != conv.id
    asyncio.run(hub.fire_schedule(item))
    reply(srv, conv, "One new email.")
    assert [u for _, u, _ in pushes] == [f"/#c={hub.main_id()}"] * 2


def test_side_chat_and_main_chat_replies_open_their_chat(srv, pushes):
    hub = srv.hub
    main = asyncio.run(hub.main_conv())
    side = asyncio.run(hub.new_conversation(title="Paper slides"))
    for conv in (side, main):
        asyncio.run(hub.submit(conv, "hi", voice=False))
        reply(srv, conv)
    assert [(t, u) for t, u, _ in pushes] == [("Paper slides", f"/#c={side.id}"), ("Main chat", f"/#c={main.id}")]


def test_compacted_main_chat_reply_opens_main_chat(srv, pushes):
    hub = srv.hub
    main = asyncio.run(hub.main_conv())
    asyncio.run(hub._new_session(main, carry="summary"))   # compaction: a new session
    asyncio.run(hub.submit(main, "hi", voice=False))
    reply(srv, main)
    assert pushes[-1][1] == f"/#c={main.id}"


def test_approval_asked_by_a_later_session_opens_its_chat(srv, pushes, monkeypatch):
    hub = srv.hub
    side = asyncio.run(hub.new_conversation(title="Job sweep"))
    asyncio.run(hub._new_session(side))
    events = []

    async def broadcast(ev):
        events.append(ev)
    monkeypatch.setattr(hub, "broadcast", broadcast)

    async def ask():
        task = asyncio.create_task(hub.on_permission(
            side.sid, {"title": "Shell", "rawInput": {"command": "rm -rf /tmp/x"}, "toolCallId": "t1"},
            [{"optionId": "allow_once"}, {"optionId": "reject_once"}]))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if pushes:
                break
        task.cancel()
    asyncio.run(ask())
    assert pushes and pushes[0][:2] == ("Needs your OK", f"/#c={side.id}")
    card = next(e["approval"] for e in events if e.get("t") == "approval")
    assert card["conv"] == side.id                       # the app finds the card's chat by its id


def test_browser_alert_opens_the_chat_that_uses_the_browser(srv, pushes, monkeypatch):
    hub = srv.hub
    monkeypatch.setattr(hub, "broadcast", lambda ev: asyncio.sleep(0))
    a = asyncio.run(hub.new_conversation(title="Job sweep"))
    b = asyncio.run(hub.new_conversation(title="Main"))
    key_a = next(k for k, v in hub.mcp_keys.items() if v == a.id)
    asyncio.run(hub._new_session(a))                     # a later run: a new key for the same chat
    key_a2 = next(k for k, v in hub.mcp_keys.items() if v == a.id and k != key_a)
    a.running = b.running = True
    b.updated = a.updated + 10                           # the Main chat spoke last
    for key in (key_a, key_a2):
        asyncio.run(hub.notify_browser("Needs you in the browser", "Log in", hub.conv_for_key(key)))
    assert [u for _, u, _ in pushes] == [f"/#c={a.id}"] * 2
    a.running = b.running = False


def test_browser_alert_with_an_unknown_key_does_not_guess_a_chat(srv, pushes, monkeypatch):
    """An unknown key while two chats run: the newest running chat is a guess and can be the wrong chat.
    Failed on the old code: conv_for_key fell back to the most recently updated running chat (#58)."""
    hub = srv.hub
    monkeypatch.setattr(hub, "broadcast", lambda ev: asyncio.sleep(0))
    a = asyncio.run(hub.new_conversation(title="Job sweep"))
    b = asyncio.run(hub.new_conversation(title="Main"))
    a.running = b.running = True
    b.updated = a.updated + 10
    asyncio.run(hub.notify_browser("Needs you in the browser", "Log in", hub.conv_for_key("stale-key")))
    assert pushes[-1][1] == "/"                          # two chats run: not the Main chat's link by guess
    a.running = b.running = False


def test_push_payload_names_the_chat_outright(srv, monkeypatch):
    """What reaches the phone: the link, and (proposed) the chat id as its own field, so the service worker does not
    have to dig it out of the link's hash. Failed on the old code: the payload had no "chat" field (#58)."""
    sent = []
    monkeypatch.setattr(srv.hub.push.subs, "data", [{"endpoint": "https://push.example/1", "keys": {}}])
    monkeypatch.setattr(srv.hub.push, "_send_all", lambda payload: sent.append(payload))
    asyncio.run(srv.hub.push.send("Email check", "Two new emails", url="/#c=20261019_28", tag=None))
    assert sent[0]["url"] == "/#c=20261019_28"
    assert sent[0].get("chat") == "20261019_28"
