"""The milo-weather MCP server: a forecast as structured data, which the app shows as a weather card.

Open-Meteo (geocoding and forecast) and, in the US, the National Weather Service's active alerts. Both are free and
need no key. Before this, Milo fetched wttr.in with WebFetch, which hands Claude only a model's summary of the page.
"""

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable

import httpx
from mcp import types
from mcp.server.lowlevel import Server

from mcp_proxy import BearerEndpoint, session_manager

log = logging.getLogger("weather-mcp")

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ALERTS = "https://api.weather.gov/alerts/active"
AGENT = "Milo/1.0 (personal assistant)"   # api.weather.gov refuses requests without a User-Agent
HOURS = 12

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
# WMO weather codes (Open-Meteo) -> words; the app picks the icon from the code
CODES = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
         51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
         61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
         71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Showers", 81: "Showers",
         82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorms",
         96: "Thunderstorms with hail", 99: "Thunderstorms with hail"}

TOOL = types.Tool(
    name="get_weather",
    description="Weather for a place: current conditions, the next hours, a daily forecast (high, low, chance of "
                "rain) and active alerts (US only). Use it for any weather question, not a web search or fetch. The "
                "app shows the result to the user as a weather card, so don't repeat it all: a short line on what "
                "matters is enough.",
    input_schema={"type": "object", "properties": {
        "location": {"type": "string", "description": "City, with state or country, e.g. 'Portland, OR' or 'Paris, France'"},
        "days": {"type": "integer", "minimum": 1, "maximum": 7, "description": "Days of forecast, today first (default 3)"},
        "units": {"type": "string", "enum": ["auto", "us", "metric"], "description": "auto: °F in the US, else °C"}},
        "required": ["location"]})

Fetch = Callable[[str, dict, dict], Awaitable[dict]]


async def http_json(url: str, params: dict, headers: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, params=params, headers=headers)
        r.raise_for_status()
        return r.json()


def text_result(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def place_name(r: dict) -> str:
    if r.get("country_code") == "US":
        state = next((k for k, v in STATES.items() if v == r.get("admin1")), r.get("admin1"))
        return f"{r['name']}, {state}" if state else r["name"]
    return ", ".join(x for x in (r["name"], r.get("country")) if x)


def pick_place(results: list[dict], qualifier: str) -> dict | None:
    """The best match for 'Portland' + 'OR': the qualifier names the state, region or country; else the biggest."""
    if not results:
        return None
    q = qualifier.strip().lower()
    if q:
        names = {q, STATES.get(q.upper(), "").lower()}
        if q in ("us", "usa", "united states"):
            names.add("united states")
        for r in results:
            if names & {str(r.get(k) or "").lower() for k in ("admin1", "admin2", "country", "country_code")}:
                return r
    return max(results, key=lambda r: r.get("population") or 0) if not q else results[0]


def rnd(x) -> int | None:
    return None if x is None else round(x)


def shape(place: dict, f: dict, alerts: list[dict], us_units: bool, days: int) -> dict:
    """Open-Meteo's arrays -> the card's data (also what Claude reads, so it stays small)."""
    cur, hourly, daily = f.get("current") or {}, f.get("hourly") or {}, f.get("daily") or {}
    now = cur.get("time") or ""
    times = hourly.get("time") or []
    start = next((i for i, t in enumerate(times) if t[:13] >= now[:13]), 0)   # from this hour on
    hours = [{"time": times[i], "temp": rnd(hourly["temperature_2m"][i]), "code": hourly["weather_code"][i],
              "rain": hourly["precipitation_probability"][i], "day": bool(hourly["is_day"][i])}
             for i in range(start, min(start + HOURS, len(times)))]
    day_list = [{"date": d, "high": rnd(daily["temperature_2m_max"][i]), "low": rnd(daily["temperature_2m_min"][i]),
                 "code": daily["weather_code"][i], "conditions": CODES.get(daily["weather_code"][i], ""),
                 "rain": daily["precipitation_probability_max"][i],
                 "sunrise": daily["sunrise"][i][-5:], "sunset": daily["sunset"][i][-5:]}
                for i, d in enumerate((daily.get("time") or [])[:days])]
    return {
        "location": place_name(place), "lat": round(place["latitude"], 3), "lon": round(place["longitude"], 3),
        "time": now, "timezone": f.get("timezone", ""), "units": "F" if us_units else "C",
        "wind_unit": "mph" if us_units else "km/h",
        "now": {"temp": rnd(cur.get("temperature_2m")), "feels": rnd(cur.get("apparent_temperature")),
                "code": cur.get("weather_code"), "conditions": CODES.get(cur.get("weather_code"), ""),
                "humidity": cur.get("relative_humidity_2m"), "wind": rnd(cur.get("wind_speed_10m")),
                "day": bool(cur.get("is_day", 1))},
        "hours": hours, "days": day_list, "alerts": alerts, "source": "Open-Meteo" + (", NWS" if alerts else "")}


class WeatherTools:
    def __init__(self, key: str, on_result: Callable[[str | None, dict, dict], Awaitable[None]] | None = None,
                 fetch: Fetch = http_json):
        self.key = key
        self.fetch = fetch
        # (chat key from the MCP URL, the call's arguments, the card's data): the bridge puts the card in the chat
        self.on_result = on_result
        self.server = Server("milo-weather", version="1.0", instructions="Weather forecasts. The app shows them as a card.",
                             on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.manager = session_manager(self.server)

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[TOOL])

    async def _call_tool(self, ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        key = ctx.request.query_params.get("k") if ctx.request is not None else None
        return await self.call(params.name, dict(params.arguments or {}), key)

    async def call(self, name: str, args: dict, key: str | None = None) -> types.CallToolResult:
        if name != TOOL.name:
            return text_result(f"Unknown tool {name}", True)
        try:
            data = await self.forecast(str(args.get("location") or ""), int(args.get("days") or 3),
                                       str(args.get("units") or "auto"))
        except LookupError as e:
            return text_result(str(e), True)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            log.warning("weather failed: %r", e)
            return text_result(f"The weather service did not answer ({type(e).__name__}). Try again later.", True)
        if self.on_result:
            try:
                await self.on_result(key, args, data)
            except Exception:
                log.exception("weather card")
        return text_result(json.dumps(data, separators=(",", ":")))

    async def forecast(self, location: str, days: int = 3, units: str = "auto") -> dict:
        name, _, qualifier = location.partition(",")
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise LookupError("Pass a location, such as 'Portland, OR'.")
        found = await self.fetch(GEOCODE, {"name": name, "count": 10, "language": "en", "format": "json"}, {})
        place = pick_place(found.get("results") or [], qualifier)
        if not place:
            raise LookupError(f"No place called {location!r} found. Try the city with its state or country.")
        us = place.get("country_code") == "US"
        us_units = us if units == "auto" else units == "us"
        days = max(1, min(days, 7))
        params = {"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
                  "forecast_days": max(days, 2),   # tomorrow's first hours for the hourly strip at night
                  "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                  "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
                  "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"}
        if us_units:
            params |= {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
        alerts_task = asyncio.create_task(self.alerts(place)) if us else None
        f = await self.fetch(FORECAST, params, {})
        alerts = await alerts_task if alerts_task else []
        return shape(place, f, alerts, us_units, days)

    async def alerts(self, place: dict) -> list[dict]:
        """Active NWS alerts at the place. Optional: a failure leaves them out, not the forecast."""
        try:
            got = await self.fetch(ALERTS, {"point": f"{place['latitude']:.4f},{place['longitude']:.4f}"},
                                   {"User-Agent": AGENT, "Accept": "application/geo+json"})
        except Exception as e:
            log.info("no NWS alerts: %r", e)
            return []
        out = []
        for feat in got.get("features") or []:
            p = feat.get("properties") or {}
            if p.get("event"):
                out.append({"event": p["event"], "severity": p.get("severity") or "",
                            "headline": (p.get("headline") or "")[:200], "ends": p.get("ends") or p.get("expires") or ""})
        return out[:3]


def weather_blocks(msg: dict) -> str:
    """A reply's weather cards as ```weather blocks, for its saved copy (the Library shows them as cards)."""
    return "".join(f"```weather\n{json.dumps(t['weather'], separators=(',', ':'))}\n```\n\n"
                   for t in msg.get("tools") or [] if t.get("weather"))


def WeatherMCPApp(tools: WeatherTools) -> BearerEndpoint:
    return BearerEndpoint(tools.manager, tools.key)
