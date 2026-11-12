"""The weather card (BEHAVIOR #87): weather_mcp.py's get_weather, and web/app.js weatherCard and the ```weather block.

Unit: get_weather with a fake fetch (no network). md() in node. e2e: the card in the real app in WebKit at iPhone size,
light and dark. The bridge side (the card on the step, the saved briefing) is in test_api.py.
"""

import asyncio
import json
import re
import shutil
import subprocess

import httpx
import pytest
from playwright.async_api import async_playwright

import weather_mcp
from conftest import ROOT
from test_rich_tables import RUNNER
from weather_mcp import ALERTS, FORECAST, GEOCODE, WeatherTools, pick_place, weather_blocks

PORTLAND_OR = {"name": "Portland", "latitude": 45.5235, "longitude": -122.6762, "country_code": "US",
               "country": "United States", "admin1": "Oregon", "admin2": "Multnomah", "population": 632309}
PORTLAND_ME = {"name": "Portland", "latitude": 43.6574, "longitude": -70.2589, "country_code": "US",
               "country": "United States", "admin1": "Maine", "admin2": "Cumberland", "population": 66881}
PARIS = {"name": "Paris", "latitude": 48.85341, "longitude": 2.3488, "country_code": "FR", "country": "France",
         "admin1": "Île-de-France", "population": 2138551}


def forecast(days=3):
    hours = [f"2026-10-26T{h:02d}:00" for h in range(24)] + [f"2026-10-27T{h:02d}:00" for h in range(24)]
    return {"timezone": "America/Los_Angeles",
            "current": {"time": "2026-10-26T09:15", "temperature_2m": 50.2, "apparent_temperature": 46.4,
                        "relative_humidity_2m": 60, "weather_code": 0, "wind_speed_10m": 5.4, "is_day": 1},
            "hourly": {"time": hours, "temperature_2m": [40 + i % 24 for i in range(48)],
                       "weather_code": [61 if i in (10, 11) else 1 for i in range(48)],
                       "precipitation_probability": [60 if i in (10, 11) else 0 for i in range(48)],
                       "is_day": [1 if 7 <= i % 24 < 18 else 0 for i in range(48)]},
            "daily": {"time": [f"2026-10-{26 + d}" for d in range(days)], "weather_code": [61, 3, 2][:days] + [0] * (days - 3),
                      "temperature_2m_max": [69.4, 66, 67][:days] + [70] * (days - 3),
                      "temperature_2m_min": [42.1, 49, 52][:days] + [50] * (days - 3),
                      "precipitation_probability_max": [60, 10, 0][:days] + [0] * (days - 3),
                      "sunrise": [f"2026-10-{26 + d}T07:28" for d in range(days)],
                      "sunset": [f"2026-10-{26 + d}T18:13" for d in range(days)]}}


class Fake:
    def __init__(self, places=(PORTLAND_ME, PORTLAND_OR), alerts=None, fail=None):
        self.places, self.alerts, self.fail, self.calls = list(places), alerts, fail, []

    async def __call__(self, url, params, headers):
        self.calls.append((url, params, headers))
        if self.fail == url:
            raise httpx.ConnectError("down")
        if url == GEOCODE:
            return {"results": self.places} if self.places else {}
        if url == FORECAST:
            return forecast(params["forecast_days"])
        if url == ALERTS:
            return {"features": [{"properties": a} for a in self.alerts or []]}
        raise AssertionError(url)


def run(coro):
    return asyncio.run(coro)


def test_pick_place_follows_the_state_or_country():
    both = [PORTLAND_OR, PORTLAND_ME]
    assert pick_place(both, " ME") is PORTLAND_ME and pick_place(both, "Maine") is PORTLAND_ME
    assert pick_place([PORTLAND_ME, PORTLAND_OR], "") is PORTLAND_OR   # no qualifier: the biggest
    assert pick_place([PARIS], "France") is PARIS and pick_place([], "VA") is None


def test_us_forecast_shape_and_alerts():
    fake = Fake(alerts=[{"event": "Flood Watch", "severity": "Moderate", "headline": "Flood Watch until 8 PM",
                         "ends": "2026-10-26T20:00:00-04:00"}, {"event": ""}])
    tools = WeatherTools("k", fetch=fake)
    w = run(tools.forecast("Portland, OR", days=3))
    assert w["location"] == "Portland, OR" and w["units"] == "F" and w["wind_unit"] == "mph"
    assert w["now"] == {"temp": 50, "feels": 46, "code": 0, "conditions": "Clear", "humidity": 60, "wind": 5, "day": True}
    assert len(w["hours"]) == weather_mcp.HOURS and w["hours"][0]["time"] == "2026-10-26T09:00"   # from this hour on
    assert w["hours"][1] == {"time": "2026-10-26T10:00", "temp": 50, "code": 61, "rain": 60, "day": True}
    assert [(d["date"], d["high"], d["low"], d["conditions"]) for d in w["days"]] == [
        ("2026-10-26", 69, 42, "Light rain"), ("2026-10-27", 66, 49, "Overcast"), ("2026-10-28", 67, 52, "Partly cloudy")]
    assert w["days"][0]["sunrise"] == "07:28"
    assert w["alerts"] == [{"event": "Flood Watch", "severity": "Moderate", "headline": "Flood Watch until 8 PM",
                            "ends": "2026-10-26T20:00:00-04:00"}]
    assert w["source"] == "Open-Meteo, NWS"
    geo, fc, al = (next(c for c in fake.calls if c[0] == u) for u in (GEOCODE, FORECAST, ALERTS))
    assert geo[1]["name"] == "Portland"                               # the qualifier is not part of the search
    assert fc[1]["temperature_unit"] == "fahrenheit" and fc[1]["timezone"] == "auto"
    assert al[1] == {"point": "45.5235,-122.6762"} and "User-Agent" in al[2]   # NWS needs one


def test_abroad_is_metric_and_has_no_nws_call():
    fake = Fake(places=[PARIS])
    w = run(WeatherTools("k", fetch=fake).forecast("Paris, France", days=1))
    assert w["location"] == "Paris, France" and w["units"] == "C" and w["wind_unit"] == "km/h"
    assert len(w["days"]) == 1 and w["alerts"] == [] and w["source"] == "Open-Meteo"
    assert ALERTS not in [c[0] for c in fake.calls] and "temperature_unit" not in fake.calls[-1][1]
    us = run(WeatherTools("k", fetch=Fake(places=[PARIS])).forecast("Paris", units="us"))
    assert us["units"] == "F"


def test_failed_alerts_leave_the_forecast():
    w = run(WeatherTools("k", fetch=Fake(fail=ALERTS)).forecast("Portland, OR"))
    assert w["alerts"] == [] and w["now"]["temp"] == 50


def test_call_errors_are_tool_errors_and_results_reach_the_bridge():
    seen = []

    async def on_result(key, args, data):
        seen.append((key, args, data["location"]))
    tools = WeatherTools("k", on_result=on_result, fetch=Fake())
    ok = run(tools.call("get_weather", {"location": "Portland, OR"}, "chat-key"))
    assert not ok.is_error and json.loads(ok.content[0].text)["location"] == "Portland, OR"
    assert seen == [("chat-key", {"location": "Portland, OR"}, "Portland, OR")]
    for args, fetch, said in [({"location": "Nowhere"}, Fake(places=[]), "No place called"),
                              ({"location": " "}, Fake(), "Pass a location"),
                              ({"location": "Portland, OR"}, Fake(fail=FORECAST), "did not answer")]:
        r = run(WeatherTools("k", on_result=on_result, fetch=fetch).call("get_weather", args, "x"))
        assert r.is_error and said in r.content[0].text, (args, r.content[0].text)
    assert len(seen) == 1                                               # no card for a failed call
    assert run(tools.call("nope", {})).is_error


def test_a_failing_card_does_not_fail_the_call():
    async def broken(*a):
        raise RuntimeError("bridge")
    r = run(WeatherTools("k", on_result=broken, fetch=Fake()).call("get_weather", {"location": "Portland, OR"}))
    assert not r.is_error


def test_tool_is_listed():
    tools = run(WeatherTools("k")._list_tools(None, None)).tools
    assert [t.name for t in tools] == ["get_weather"] and tools[0].input_schema["required"] == ["location"]


def test_weather_blocks_for_a_saved_reply():
    w = run(WeatherTools("k", fetch=Fake()).forecast("Portland, OR"))
    text = weather_blocks({"tools": [{"id": "a"}, {"id": "b", "weather": w}]})
    assert text.startswith("```weather\n{") and text.endswith("\n```\n\n")
    assert json.loads(text.split("\n")[1]) == w
    assert weather_blocks({"tools": []}) == "" and weather_blocks({}) == ""


# md(): a ```weather block in a saved briefing is the same card

# RUNNER also takes the multi-line consts the card needs (the icons)
WX_RUNNER = RUNNER.replace(
    "  } else if (/^(async )?function /.test(l)) {",
    "  } else if (/^const WX_\\w+ = \\{$/.test(l)) {\n"
    "    let j = i; while (j < lines.length && lines[j] !== '};') j++;\n"
    "    code.push(lines.slice(i, j + 1).join('\\n').replace(/^const /, 'var ')); i = j;\n"
    "  } else if (/^(async )?function /.test(l)) {")


def md(*cases):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    r = subprocess.run(["node", "-e", WX_RUNNER, str(ROOT / "web" / "app.js")], input=json.dumps(cases),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_weather_block_is_a_card():
    w = run(WeatherTools("k", fetch=Fake(alerts=[{"event": "Flood <Watch>", "ends": ""}])).forecast("Portland, OR"))
    block = weather_blocks({"tools": [{"weather": w}]})
    card, cut, bad, other = md([block + "Rain later.", False], [block[:40], True], ["```weather\nnot json\n```", False],
                               ["```weather\n{\"a\": 1}\n```", False])
    assert card.startswith('<div class="wx" role="group" aria-label="Weather for Portland, OR">')
    assert card.endswith("<p>Rain later.</p>")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", card))
    assert "50°" in text and "Clear" in text and "H 69° L 42°" in text and "Flood &lt;Watch&gt;" in text
    assert "Now" in text and "Today" in text and "60%" in text   # the hourly strip, the days, a rain chance
    assert card.count('class="wx-h"') == 6 and card.count('class="wx-day"') == 3
    assert 'class="wx-i rain"' in card and 'class="wx-i sun"' in card
    assert 'class="wx wx-wait"' in cut and "{" not in re.sub(r"<[^>]+>", "", cut)   # streaming: no raw JSON
    assert "<pre" in bad and "not json" in bad and "<pre" in other     # not ours: shown as code


def test_night_dry_card_has_no_rain_row():
    w = run(WeatherTools("k", fetch=Fake()).forecast("Portland, OR"))
    w["now"]["day"] = False
    for h in w["hours"]:
        h["rain"] = 0
    [card] = md([weather_blocks({"tools": [{"weather": w}]}), False])
    head = card.split('class="wx-hours"')[0]
    assert 'class="wx-i moon"' in head and "<small>" not in card


# e2e: the card on a step of a reply, in the app at iPhone size

from test_bridge_e2e import FAKE_CHAT, bridge, phone_page  # noqa: E402,F401  (the test bridge, own port and data)


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("scheme", ["light", "dark"])
async def test_weather_card_in_the_chat(bridge, scheme):
    w = await WeatherTools("k", fetch=Fake(alerts=[{"event": "Wind Advisory", "ends": ""}])).forecast("Portland, OR")
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, color_scheme=scheme)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""(w) => { S.conv.messages.push({ role: 'user', text: 'Weather?' },
            { role: 'assistant', text: 'Rain around 10, then clear.', notes: [],
              tools: [{ id: 't1', title: 'Weather', status: 'completed', detail: 'Portland, OR', at: 0, weather: w }] });
            renderMessages(true); }""", w)
        card = page.locator(".msg.assistant .wx").last
        m = await card.evaluate("""(c) => { const r = c.getBoundingClientRect(), msg = c.closest('.msg').getBoundingClientRect();
            const bub = c.parentElement.querySelector('.bubble'), cs = getComputedStyle(c), body = getComputedStyle(document.body);
            const kids = [...c.querySelectorAll('*')].map((e) => e.getBoundingClientRect());
            return { inside: r.left >= msg.left - 0.5 && r.right <= msg.right + 0.5 && r.right <= innerWidth,
              overflow: kids.some((k) => k.right > r.right + 0.5 || k.left < r.left - 0.5),
              pageWide: document.documentElement.scrollWidth > innerWidth, above: r.bottom <= bub.getBoundingClientRect().top,
              bg: cs.backgroundColor, ink: getComputedStyle(c.querySelector('.wx-temp')).color, bodyInk: body.color,
              sun: getComputedStyle(c.querySelector('.wx-i.sun')).color, hours: c.querySelectorAll('.wx-h').length,
              alert: c.querySelector('.wx-alert')?.textContent.trim(), steps: !!c.closest('.msg').querySelector('.steps') }; }""")
        assert m["inside"] and not m["overflow"] and not m["pageWide"] and m["above"], m
        assert m["hours"] == 6 and m["alert"] == "Wind Advisory" and m["steps"], m
        dark = scheme == "dark"
        lum = lambda c: sum(int(x) for x in re.findall(r"\d+", c)[:3])  # noqa: E731
        assert (lum(m["bg"]) < 300) == dark and (lum(m["ink"]) > 450) == dark, m   # follows the theme
        assert m["sun"] not in (m["ink"], m["bodyInk"]), m                # the sun has its own color

        # a result that comes in while the reply runs replaces its step (the "tool" event)
        await page.evaluate("""(w) => { const msg = S.conv.messages.at(-1);
            msg.tools = [{ id: 'wx-1', title: 'Weather', status: 'completed', detail: 'Portland, OR', at: 0, weather: w }];
            renderMessages(); handle({ t: 'tool', id: S.current, replaces: 'wx-1',
              tool: { id: 't9', title: 'Weather', status: 'completed', detail: 'Portland, OR', at: 0, weather: w } }); }""", w)
        await page.wait_for_timeout(300)
        ids = await page.evaluate("S.conv.messages.at(-1).tools.map((t) => t.id)")
        assert ids == ["t9"] and await page.locator(".msg.assistant .wx").count() == 1
        assert errors == []
        await b.close()
