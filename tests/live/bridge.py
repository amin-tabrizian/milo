"""The eval bridge: the real server.py (same Hub, prompts, milo_context, tags and goose/claude-acp session plumbing) on
the sandbox's data, with the parts that reach the outside swapped out:

- milo-google answers from fixtures (fake_google.py); sends, drafts and event changes are recorded, never made.
- milo-weather answers with a fixed rainy forecast for any place (no network); its calls are recorded.
- No pushes, no scheduler firing, no browser, no whisper/voice model, no chat-title or reaction calls.
- <restart/> is recorded; the bridge does not restart.
- Each reply keeps its raw text (with the tags) in message["raw"], for the graders.

  MILO_DATA_DIR=<base>/data MILO_CLAUDE_DIR=<milo>/data/claude python tests/live/bridge.py --base <base>
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
opts = ap.parse_args()
BASE = Path(opts.base)

import server  # noqa: E402  (reads MILO_DATA_DIR at import)
from fake_google import ACCOUNTS, FakeGoogle  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from sandbox import reset_files  # noqa: E402

hub = server.hub
fake = FakeGoogle()
restarts: list[dict] = []


async def noop(*args, **kwargs):
    return None


# milo-google: the real MCP server object and tool list, answered by the fake
hub.google.client = lambda: ("eval", "eval")
hub.google.up.tools = fake.tools
hub.google.up.start = noop
hub.google.up.stop = noop
hub.google.accounts.data = [{**a, "added": time.time()} for a in ACCOUNTS]
hub.google.connected = lambda email: True
hub.google.call = fake.call

# milo-planner: the real tools on the fake calendars, the sandbox's Tasks.md and rules, and a fixed work feed
busy_days: dict = {}


def busy_fixture() -> dict:
    """busy.json around today: a 10:00-11:00 work meeting tomorrow, 10:00-10:30 the day after."""
    day = datetime.now().date()
    return {(day + timedelta(days=1)).isoformat(): [[600, 660]], (day + timedelta(days=2)).isoformat(): [[600, 630]]}


async def fake_busy(url: str) -> dict:
    return {"days": busy_days}


hub.planner.fetch = fake_busy
hub.planner.busy_url = "https://calendar.example.com/busy.json"   # fake_busy answers it
hub.planner.busy_url = "fake://busy.json"   # read from fake_busy, whatever config.json says

# milo-weather: the real tool and card plumbing on a fixed forecast
weather_calls: list[dict] = []


async def fake_weather(url, params, headers):
    import weather_mcp
    now = datetime.now()
    if url == weather_mcp.GEOCODE:
        weather_calls.append({"ts": time.time(), "name": params.get("name")})
        return {"results": [{"name": params.get("name") or "Portland", "latitude": 45.52, "longitude": -122.68,
                             "country_code": "US", "admin1": "Oregon", "population": 1}]}
    if url == weather_mcp.ALERTS:
        return {"features": []}
    days = [(now.date() + timedelta(days=i)).isoformat() for i in range(params["forecast_days"])]
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    return {"timezone": "America/New_York",
            "current": {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 52, "apparent_temperature": 49,
                        "relative_humidity_2m": 80, "weather_code": 61, "wind_speed_10m": 9, "is_day": 1},
            "hourly": {"time": hours, "temperature_2m": [52] * len(hours), "weather_code": [61] * len(hours),
                       "precipitation_probability": [70] * len(hours), "is_day": [1] * len(hours)},
            "daily": {"time": days, "weather_code": [63] + [2] * (len(days) - 1), "temperature_2m_max": [58] * len(days),
                      "temperature_2m_min": [44] * len(days), "precipitation_probability_max": [80] + [10] * (len(days) - 1),
                      "sunrise": [f"{d}T07:28" for d in days], "sunset": [f"{d}T18:13" for d in days]}}


hub.weather.fetch = fake_weather

# nothing leaves the Mac, nothing runs on its own
hub.notify = noop
hub.whisper.start = noop
hub.whisper.stop = noop
hub.neural.voices = lambda: []
hub.scheduler.start = lambda: None


def restart_soon(cid: str) -> None:
    restarts.append({"ts": time.time(), "conv": cid})


hub.restart_soon = restart_soon


async def name_chat(conv, text):
    hub.naming.pop(conv.id, None)


hub._name_chat = name_chat

_finish = hub._finish


async def finish(conv, stop, error, voice):
    msg = hub._assistant_msg(conv)
    msg["raw"] = msg["text"]   # before the tags are taken out
    await _finish(conv, stop, error, voice)


hub._finish = finish


# eval routes (behind the token, as every /api route)

async def eval_reset():
    reset_files(BASE)
    pristine = BASE / "pristine"
    hub.memory.write((pristine / "memory.md").read_text() if (pristine / "memory.md").exists() else "")
    hub.goals.store.data = json.loads((pristine / "goals.json").read_text()) if (pristine / "goals.json").exists() else []
    hub.goals._changed()
    items = json.loads((pristine / "schedules.json").read_text()) if (pristine / "schedules.json").exists() else []
    for item in items:
        if item.get("enabled", True) and item.get("cron"):
            item["next"] = hub.scheduler._next_cron(item["cron"])
    hub.scheduler.store.data = items
    hub.scheduler.store.save()
    hub.scheduler.version = time.time()
    fake.reset()
    busy_days.clear()
    busy_days.update(busy_fixture())
    restarts.clear()
    weather_calls.clear()
    for cid in [c.id for c in hub.convs.values() if not c.running]:   # every case starts with no chats (a new Main chat)
        hub.convs.pop(cid)
    hub.save()
    return {"ok": True}


async def eval_setup(setup: dict):
    """A case's own state, after the reset: more calendar events, Google tools that fail, and to-dos under Open."""
    fake.add_events(setup.get("events") or [])
    for offset, blocks in (setup.get("busy") or {}).items():   # {days from today: [[start min, end min]]}
        busy_days[(datetime.now().date() + timedelta(days=int(offset))).isoformat()] = blocks
    fake.fail = set(setup.get("fail") or [])
    if lines := setup.get("tasks"):
        tasks = BASE / "work" / "Library" / "Planner" / "Tasks.md"
        text = tasks.read_text()
        head = "## Open\n"
        tasks.write_text(text.replace(head, head + "".join(f"{ln}\n" for ln in lines), 1) if head in text
                         else text.rstrip("\n") + "\n" + "".join(f"{ln}\n" for ln in lines))
    return {"ok": True}


async def eval_info():
    return {"google_calls": fake.calls, "google_messages": fake.drafts, "restarts": restarts,
            "weather_calls": weather_calls,
            "schedules": hub.scheduler.store.data, "memory": hub.memory.read(), "goals": hub.goals.store.data,
            "busy": [c.id for c in hub.convs.values() if c.running or c.compacting]}


for path, fn, methods in (("/api/eval/reset", eval_reset, ["POST"]), ("/api/eval/setup", eval_setup, ["POST"]),
                          ("/api/eval/info", eval_info, ["GET"])):
    # before the app's catch-all static mount at "/"
    server.app.router.routes.insert(0, APIRoute(path, fn, methods=methods))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(server.app, host="127.0.0.1", port=server.CFG["port"], log_level="warning")
