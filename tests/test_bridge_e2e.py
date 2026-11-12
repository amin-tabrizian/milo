"""Whole-stack tests against a separate test bridge (port 8797, headless Chrome on 9447, temporary data).

  uv run pytest -m e2e     phone viewer: live picture, take control, tap, give back (no AI model)
  uv run pytest -m agent   real tasks through goose and Claude: approvals, saved login, takeover, no secret leaks
"""

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import websockets
from playwright.async_api import async_playwright

from conftest import ROOT, TEST_PASSWORD

# MILO_TEST_PORT and friends: a second run at the same time (another session) needs ports of its own
PORT, CDP_PORT, WHISPER_PORT = (int(os.environ.get(k, d)) for k, d in (("MILO_TEST_PORT", 8797), ("MILO_TEST_CDP_PORT", 9447),
                                                                  ("MILO_TEST_WHISPER_PORT", 8179)))
TOKEN = "bridge-test-token"
WHISPER_MODEL = ROOT / "models" / "ggml-large-v3-turbo-q5_0.bin"
BASE = f"http://127.0.0.1:{PORT}"
H = {"Authorization": f"Bearer {TOKEN}"}
pytestmark = pytest.mark.asyncio(loop_scope="module")


def feed_post(pid, handle, text):
    return {"id": pid, "handle": handle, "name": handle.title(), "text": text, "created": time.time() - 7200, "avatar": "",
            "url": f"https://x.com/{handle}/status/{pid}", "followers": 9000, "following": True, "likes": 1200, "reposts": 80,
            "replies": 30, "quotes": 4, "views": 50000, "media": [], "link": None, "quote": None, "reposted_by": None, "reply": False}


FEED_POSTS = [feed_post("f1", "openai", "We shipped a new reasoning model today."), feed_post("f2", "researcher", "Early evals look strong."),
              feed_post("f3", "evalsguy", "Benchmark audit: 18% of answers leaked."), feed_post("g1", "labhead", "Hiring for safety research."),
              feed_post("n1", "senatepress", "The Senate passed the budget 52-48.")]
FEED = {"generated": time.time(), "status": {"state": "ok", "detail": "", "checked": time.time()}, "settings": {}, "tabs": {
    "foryou": {"generated": time.time(), "read": 140, "posts": {p["id"]: p for p in FEED_POSTS[:3]},
               "brief": [{"title": "OpenAI ships a reasoning model", "text": "OpenAI shipped a new reasoning model.", "posts": ["f1", "f2"],
                          "media": None},
                         {"text": "An audit found leaked benchmark answers.", "posts": ["f3"], "media": None}],
               "top": [{"post": "f1", "why": "Original source for the launch."}, {"post": "f3", "why": "Bears on eval trust."}]},
    "following": {"generated": time.time(), "read": 30, "posts": {"g1": FEED_POSTS[3]},
                  "brief": [{"text": "A lab is hiring for safety research.", "posts": ["g1"], "media": None}],
                  "top": [{"post": "g1", "why": "Fits your safety work."}]},
    "politics": {"generated": time.time(), "read": 140, "posts": {"n1": FEED_POSTS[4]},
                 "brief": [{"title": "Senate passes the budget", "text": "The vote was 52 to 48.", "posts": ["n1"], "media": None}],
                 "top": [{"post": "n1", "why": ""}]}}}


# test_read_state_is_shared_across_devices: a reply came after the user last read "shared"; "legacy" was saved before
# the read marker was kept (no "read"), so it counts as read
SEEN_CHATS = [
    {"id": "shared", "title": "Shared chat", "source": "app", "created": time.time() - 600, "updated": time.time() - 60,
     "read": time.time() - 300, "messages": [{"role": "user", "text": "Hi", "ts": time.time() - 90},
                                             {"role": "assistant", "text": "A new reply.", "ts": time.time() - 60}]},
    {"id": "legacy", "title": "Old chat", "source": "app", "created": time.time() - 9000, "updated": time.time() - 8000,
     "messages": [{"role": "user", "text": "Old", "ts": time.time() - 8000}]}]


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    data = tmp_path_factory.mktemp("bridge")
    (data / "config.json").write_text(json.dumps({
        "token": TOKEN, "port": PORT, "browser_port": CDP_PORT, "browser_headless": True,
        "whisper_model": str(WHISPER_MODEL), "whisper_port": WHISPER_PORT, "library_dir": str(data / "lib"), "goose_cwd": str(data)}))
    # two ready ideas, so opening Ideas does not ask the AI for new ones
    (data / "ideas.json").write_text(json.dumps({"generated": time.time(), "items": [
        {"id": "i-1", "title": "I can plan your week", "detail": "From your calendar.", "prompt": "Plan my week", "emoji": "🗓️"},
        {"id": "i-2", "title": "I can tidy your downloads", "detail": "Big old files.", "prompt": "Tidy Downloads", "emoji": "🧹"}]}))
    (data / "feed.json").write_text(json.dumps(FEED))   # a fresh feed, so the bridge never reads X
    (data / "conversations.json").write_text(json.dumps(SEEN_CHATS))
    # own copy, so file changes in tests never reach your phone (MILO_WEB_SRC: test another copy of the app)
    web = shutil.copytree(os.environ.get("MILO_WEB_SRC") or ROOT / "web", data / "web")
    env = {**os.environ, "MILO_DATA_DIR": str(data), "MILO_WEB_DIR": str(web),
           "MILO_CLAUDE_DIR": str(ROOT / "data" / "claude"),            # Milo's signed-in Claude profile, for agent tests
           "MILO_KEYCHAIN_SERVICE": f"Milo-bridge-{uuid.uuid4().hex[:8]}"}
    log = open(data / "bridge.log", "w")
    proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        for _ in range(240):
            try:
                st = httpx.get(f"{BASE}/api/browser/state", headers=H, timeout=1).json()
                if st.get("ready"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("test bridge did not start:\n" + (data / "bridge.log").read_text()[-3000:])
        yield {"data": data, "log": data / "bridge.log", "web": web}
    finally:
        for acct in httpx.get(f"{BASE}/api/accounts", headers=H).json() if proc.poll() is None else []:
            httpx.delete(f"{BASE}/api/accounts/{acct['id']}", headers=H)
        proc.terminate()
        proc.wait(10)
        subprocess.run(["pkill", "-f", f"remote-debugging-port={CDP_PORT}"], check=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def remote():
    """Our own CDP connection to the bridge's Chrome, to check page state from outside."""
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    yield browser
    await pw.stop()


async def page_with(remote, part, timeout=20):
    for _ in range(timeout * 4):
        for p in remote.contexts[0].pages:
            if part in p.url:
                return p
        await asyncio.sleep(0.25)
    raise AssertionError(f"no tab with {part}")


async def api(method, path, **kw):
    async with httpx.AsyncClient(base_url=BASE, headers=H, timeout=30) as c:
        r = await c.request(method, path, **kw)
        r.raise_for_status()
        return r.json()


# phone viewer (no AI)


@pytest.mark.e2e
async def test_phone_viewer_take_control_and_tap(bridge, remote, site_url, tmp_path):
    await api("POST", "/api/browser/control", json={"action": "take"})
    await api("POST", "/api/browser/navigate", json={"url": f"{site_url}/shop.html"})
    shop = await page_with(remote, "shop.html")
    box = await shop.locator("#wish").bounding_box()
    vw = await shop.evaluate("window.innerWidth")
    before = int(await shop.text_content("#wished"))

    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                  has_touch=True)
        phone = await ctx.new_page()
        await phone.goto(f"{BASE}/#token={TOKEN}")
        await phone.click("#moreBtn")
        await phone.click("[data-more=browser]")
        await phone.wait_for_function("document.querySelector('#bvImg').naturalWidth > 0", timeout=15000)
        assert await phone.text_content("#bvControl") == "Give back to Milo"
        assert "shop.html" in await phone.input_value("#bvUrl")
        await phone.screenshot(path=str(tmp_path / "viewer.png"))
        img = await phone.locator("#bvImg").bounding_box()
        scale = img["width"] / vw
        await phone.mouse.click(img["x"] + (box["x"] + box["width"] / 2) * scale,
                                img["y"] + (box["y"] + box["height"] / 2) * scale)
        for _ in range(20):
            if int(await shop.text_content("#wished")) == before + 1:
                break
            await asyncio.sleep(0.25)
        assert int(await shop.text_content("#wished")) == before + 1
        await phone.click("#bvControl")
        await phone.wait_for_function("document.querySelector('#bvControl').textContent === 'Take control'")
        await b.close()
    assert (await api("GET", "/api/browser/state"))["controller"] == "milo"


@pytest.mark.e2e
async def test_phone_reloads_when_web_files_change(bridge):
    """Edit a web file: an idle phone reloads at once; while you type it waits, and your text survives."""
    icon = bridge["web"] / "icon.svg"
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        phone = await (await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)).new_page()
        await phone.goto(f"{BASE}/#token={TOKEN}")
        await phone.wait_for_function("Update.version && S.wsOpen")
        v1 = await phone.evaluate("Update.version")
        await phone.evaluate("window.stale = true")
        await phone.fill("#input", "half-typed")                  # typing: the box has focus
        icon.write_text("<svg/>")
        await phone.wait_for_function("Update.pending", timeout=10000)
        await asyncio.sleep(2.5)
        assert await phone.evaluate("window.stale === true")       # busy: no reload yet
        await phone.evaluate("input.blur()")                       # done typing, message not sent
        await phone.wait_for_function("window.stale !== true", timeout=10000)
        await phone.wait_for_function("Update.version && S.wsOpen")
        assert await phone.evaluate("Update.version") != v1
        assert await phone.input_value("#input") == "half-typed"
        await b.close()


@pytest.mark.e2e
async def test_mic_dictates_into_the_box(bridge, tmp_path):
    """Hold the mic: words appear in the message box as you talk, with no overlay. Release: it stops, you send."""
    if not WHISPER_MODEL.exists():
        pytest.skip("no Whisper model")
    wav = tmp_path / "speech.wav"
    subprocess.run(["say", "-o", str(wav), "--data-format=LEI16@44100",
                    "Please remind me to buy oat milk and bread tomorrow morning at eight."], check=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={wav}"])
        phone = await (await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                                           permissions=["microphone"])).new_page()
        await phone.goto(f"{BASE}/#token={TOKEN}")
        await phone.wait_for_function("S.wsOpen && S.voiceInput")
        await phone.evaluate("window.sendPrompt = (text, voice) => { window.sent = [text, voice]; return true; }; 0")
        await phone.locator("#micBtn").dispatch_event("pointerdown")
        await phone.wait_for_function("/milk/i.test(document.querySelector('#input').value)", timeout=20000)
        assert await phone.evaluate("ptt.active")                       # still held: this is a live update
        assert await phone.is_visible("#micBtn") and await phone.is_hidden("#sendBtn")
        assert await phone.evaluate("!document.querySelector('.ptt')")   # no overlay
        await phone.locator("#micBtn").dispatch_event("pointerup")
        await phone.wait_for_function("!ptt.active && !ptt.finishing", timeout=20000)
        text = await phone.input_value("#input")
        assert "milk" in text.lower(), text
        assert await phone.evaluate("window.sent") is None
        await phone.click("#sendBtn")
        assert await phone.evaluate("window.sent") == [text.strip(), True]
        assert await phone.input_value("#input") == ""
        await b.close()


@pytest.mark.e2e
async def test_reply_is_spoken_part_by_part(bridge):
    """A long reply plays as several parts, one after another, in the natural voice."""
    text = " ".join(f"Here is point number {i}, and it matters for your plan." for i in range(1, 9))
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        phone = await (await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)).new_page()
        audio = []
        phone.on("response", lambda r: r.url.endswith("/api/tts") and audio.append(r.headers.get("content-type")))
        await phone.goto(f"{BASE}/#token={TOKEN}")
        await phone.wait_for_function("S.wsOpen")
        await phone.evaluate("""() => { window.played = []; const play = player.play.bind(player);
            player.play = () => { window.played.push(player.src); player.playbackRate = 16; return play(); }; }""")
        await asyncio.wait_for(phone.evaluate(f"speak({json.dumps(text)})"), 60)
        parts = len([a for a in audio if a == "audio/mp4"])
        assert parts >= 3 and len(await phone.evaluate("window.played")) == parts
        await b.close()


# phone app layout and feel (no AI model)

FAKE_KEYBOARD = """(h) => { const f = new EventTarget(); f.height = innerHeight - h; f.offsetTop = 0;
  Object.defineProperty(window, 'visualViewport', { configurable: true, get: () => f }); fitViewport(); }"""
FAKE_CHAT = """() => {
  S.convs = [{ id: 'a', title: 'Plan my week', preview: 'Here is the plan', updated: 100, read: 100, running: false, source: 'app' },
             { id: 'b', title: 'Diet', preview: 'Eat more fiber', updated: 200, read: 100, running: false, source: 'app' }];
  S.current = 'a'; S.onMain = false; S.tab = 'chat';   // a side chat
  S.conv = { messages: [{ role: 'user', text: 'Plan my week' }, { role: 'assistant', text: 'Sure.', tools: [], notes: [] }] };
  renderAll();
}"""


async def phone_page(p, engine="webkit", **kw):
    if engine == "webkit":
        b = await p.webkit.launch()
        ctx = await b.new_context(**{**p.devices["iPhone 15 Pro"], **kw})   # kw may change the viewport
    else:
        b = await p.chromium.launch(channel="chrome")
        ctx = await b.new_context(viewport={"width": 393, "height": 852}, is_mobile=True, has_touch=True, **kw)
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(f"{BASE}/#token={TOKEN}")
    await page.wait_for_function("S.wsOpen")
    return b, page, errors


@pytest.mark.e2e
async def test_splash_says_hi_once_then_gets_out_of_the_way(bridge):
    """The 3D dog plays on launch (tests normally skip it), then removes itself; a reload skips it."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false })")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        assert await page.evaluate("!!document.getElementById('splash')")
        await page.wait_for_function("!document.getElementById('splash')", timeout=8000)
        await page.reload()
        await page.wait_for_function("S.wsOpen")
        assert await page.evaluate("!document.getElementById('splash')")      # once per launch
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_header_dog_says_what_milo_is_doing(bridge):
    """The 3D dog loads in the header, and the pill says what Milo is doing in one word, then the name again.
    Each word stays at least 1.5 s; a step quicker than that is skipped."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.wait_for_function("$('.avatar-face').classList.contains('live')", timeout=15000)
        await page.evaluate(FAKE_CHAT)
        name = await page.evaluate("S.settings.assistant_name || 'Milo'")
        await page.evaluate("""() => { window.seen = [];
          new MutationObserver(() => seen.push($('#title').textContent)).observe($('#title'), { childList: true, characterData: true, subtree: true }); }""")
        said = lambda word: page.wait_for_function(f"$('#title').textContent === {word!r}", timeout=5000)
        await page.evaluate("() => { S.conv.messages.push({ role: 'user', text: 'Book a table' }); curConv().running = true; setStatus(); }")
        await said("Thinking")
        await page.evaluate("() => { S.conv.messages.push({ role: 'assistant', text: '', tools: [{ id: 't', status: 'in_progress', browser: true }], notes: [] }); setStatus(); }")
        await said("Browsing")
        assert await page.evaluate("Ava.state") == "browsing"   # the dog's lid shows a globe
        await page.evaluate("""() => { const m = S.conv.messages.at(-1); m.tools[0].status = 'completed'; m.text = 'Hi'; setStatus();
          curConv().running = false; setStatus(); }""")   # Writing lasts less than the hold
        await said(name)
        seen = [w for i, w in enumerate(await page.evaluate("seen")) if i == 0 or w != (await page.evaluate("seen"))[i - 1]]
        assert seen[-3:] == ["Thinking", "Browsing", name] and "Writing" not in seen
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_header_dog_keeps_its_face_to_you(bridge):
    """While Milo is idle, the dog turns against the phone's turn: the phone rotated left (counterclockwise), the head
    tilts clockwise. iOS's motion permission is asked on the first tap of each launch. When Milo
    works, the sensors stop."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("""
          window.asked = 0; window.listening = 0;
          if (!window.DeviceOrientationEvent) window.DeviceOrientationEvent = class extends Event {};
          DeviceOrientationEvent.requestPermission = () => { asked++; return Promise.resolve('granted'); };
          const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
          EventTarget.prototype.addEventListener = function (t, ...r) { if (t === 'deviceorientation') listening++; return add.call(this, t, ...r); };
          EventTarget.prototype.removeEventListener = function (t, ...r) { if (t === 'deviceorientation') listening--; return rem.call(this, t, ...r); };
          window.tilt = (alpha, beta, gamma) => { const e = new Event('deviceorientation');
            Object.defineProperties(e, { alpha: { value: alpha }, beta: { value: beta }, gamma: { value: gamma } }); dispatchEvent(e); };""")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("Ava.dog && Ava.state === 'idle' && listening === 1", timeout=15000)
        assert await page.evaluate("asked") == 0
        await page.touchscreen.tap(200, 500)
        await page.wait_for_function("asked === 1")
        await page.touchscreen.tap(200, 520)                               # once a launch
        await page.wait_for_timeout(300)
        assert await page.evaluate("asked") == 1
        await page.reload()                                                # iOS forgot it: the next launch asks again
        await page.wait_for_function("Ava.dog && Ava.state === 'idle' && listening === 1", timeout=15000)
        await page.touchscreen.tap(200, 500)
        await page.wait_for_function("asked === 1")                        # a "no" asks again too: see the next test

        async def hold(angles, secs):   # the phone's angles, 30 times a second
            for _ in range(int(secs * 30)):
                await page.evaluate(f"tilt({angles})")
                await asyncio.sleep(1 / 30)
        roll = "Math.round(Ava.dog.parts.head.rotation.z * 1000) / 1000"
        await hold("0, 70, 0", 1)                       # the usual hold
        straight = await page.evaluate(roll)
        await hold("38.08, 65.19, -35.42", 0.8)         # the same, rotated 15 degrees to the left
        assert await page.evaluate(roll) < straight - 0.08
        await page.evaluate("Ava.dog.set('thinking')")
        assert await page.evaluate("listening") == 0
        await page.evaluate("Ava.dog.set('idle')")
        assert await page.evaluate("listening") == 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_header_dog_works_at_a_laptop(bridge):
    """While Milo works, browses or writes, a laptop rises into the dog's paws and the look (tilt and finger) is off.
    Thinking shows a thought bubble instead. After the task the laptop sinks away, then the look comes back and the dog
    stops drawing."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("""
          window.listening = 0; window.frames = 0;
          const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
          const sensor = (t) => t === 'deviceorientation' || t === 'pointermove';
          EventTarget.prototype.addEventListener = function (t, ...r) { if (sensor(t) && this === window) listening++; return add.call(this, t, ...r); };
          EventTarget.prototype.removeEventListener = function (t, ...r) { if (sensor(t) && this === window) listening--; return rem.call(this, t, ...r); };
          const raf = requestAnimationFrame.bind(window);
          window.requestAnimationFrame = (f) => { if ((new Error().stack || '').includes('mascot.js')) frames++; return raf(f); };""")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("Ava.dog && Ava.state === 'idle' && listening === 2", timeout=15000)
        lap, bubble = "Ava.dog.props.lap.g.visible", "Ava.dog.props.bub.g.visible"
        assert not await page.evaluate(lap) and not await page.evaluate(bubble)
        await page.evaluate("Ava.dog.set('thinking')")
        await page.wait_for_function(f"{bubble} && Ava.dog.props.P.bub.x === 1", timeout=5000)
        assert not await page.evaluate(lap) and await page.evaluate("listening") == 0
        for state in ["working", "browsing", "writing", "waiting"]:
            await page.evaluate(f"Ava.dog.set({state!r})")
            assert await page.evaluate("listening") == 0, state
            await page.wait_for_function(f"{lap} && Ava.dog.props.P.lap.x === 1 && Ava.dog.props.lap.hinge.rotation.x < -1.7", timeout=5000)
        await page.wait_for_function(f"!{bubble}", timeout=5000)
        await page.evaluate("Ava.dog.set('idle')")
        assert await page.evaluate("listening") == 0   # not while the laptop is still in the paws
        await page.wait_for_function(f"!{lap} && listening === 2", timeout=5000)
        for _ in range(8):                             # after the hop it goes still: at most a blink in a second
            f0 = await page.evaluate("frames")
            await asyncio.sleep(1)
            if await page.evaluate("frames") - f0 <= 6:
                break
        else:
            raise AssertionError("the dog keeps drawing while still")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_header_dog_ignores_a_sensor_restart(bridge):
    """iOS restarts the motion sensor after a pause, and alpha then starts from 0 again wherever the phone points. A
    reading that jumps further than a hand turns between two readings, or one after a gap, is a new start: the dog keeps
    its face to you instead of swinging away and taking seconds to come back."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("""
          if (!window.DeviceOrientationEvent) window.DeviceOrientationEvent = class extends Event {};
          DeviceOrientationEvent.requestPermission = () => Promise.resolve('granted');
          window.tilt = (alpha, beta, gamma) => { const e = new Event('deviceorientation');
            Object.defineProperties(e, { alpha: { value: alpha }, beta: { value: beta }, gamma: { value: gamma } }); dispatchEvent(e); };""")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("Ava.dog && Ava.state === 'idle'", timeout=15000)

        async def hold(angles, secs):   # the phone's angles, 30 times a second
            for _ in range(int(secs * 30)):
                await page.evaluate(f"tilt({angles})")
                await asyncio.sleep(1 / 30)
        head = "(() => { const r = Ava.dog.parts.head.rotation; return [r.x, r.y, r.z]; })()"
        await hold("140, 60, 0", 1.5)                 # turned 140 degrees since the sensor started
        straight = await page.evaluate(head)
        await hold("0, 60, 0", 0.6)                   # the sensor restarted: same hold, alpha from 0 again
        moved = max(abs(a - b) for a, b in zip(await page.evaluate(head), straight))
        assert moved < 0.05, moved                    # it swung about 0.3 rad (17 degrees) before
        await hold("0, 60, 0", 0.5)
        await asyncio.sleep(1)                        # a gap: the sensor was paused
        await hold("200, 45, 10", 0.6)                # and comes back somewhere else
        moved = max(abs(a - b) for a, b in zip(await page.evaluate(head), straight))
        assert moved < 0.05, moved
        await hold("206, 45, 10", 0.6)                # a real turn of the phone still turns the dog
        assert max(abs(a - b) for a, b in zip(await page.evaluate(head), straight)) > 0.03
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_header_dog_looks_after_motion_was_denied(bridge):
    """One "Don't Allow" (or Cancel) on the motion prompt was kept for good, so the app never asked again and the dog
    stopped turning its head. Each launch asks again on the first tap; without the tilt the dog follows a finger
    anywhere on the screen, and after the menu closes it looks again."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("""
          localStorage.setItem('motion', 'denied');   // kept by the old app
          if (!window.DeviceOrientationEvent) window.DeviceOrientationEvent = class extends Event {};
          window.asked = 0;
          DeviceOrientationEvent.requestPermission = () => (asked++, Promise.resolve('denied'));
          window.finger = (type, x, y) => dispatchEvent(new PointerEvent(type, { clientX: x, clientY: y, bubbles: true }));""")
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("Ava.dog && Ava.state === 'idle'", timeout=15000)
        assert await page.evaluate("localStorage.getItem('motion')") is None   # the old "no" is dropped
        await page.touchscreen.tap(200, 500)                          # the first tap asks, though a "no" was stored
        await page.wait_for_function("asked === 1")
        await page.touchscreen.tap(200, 520)                          # once a launch
        await page.wait_for_timeout(300)
        assert await page.evaluate("asked") == 1

        yaw = "Ava.dog.parts.head.rotation.y"
        await asyncio.sleep(1.5)                                      # back from looking at the taps
        rest = await page.evaluate(yaw)
        await page.evaluate("finger('pointerdown', 380, 700)")       # far from the dog, lower right: no tilt, still looks
        await page.wait_for_function(f"{yaw} - {rest} > 0.15", timeout=3000)
        await page.evaluate("finger('pointerup', 380, 700)")
        await page.wait_for_function(f"Math.abs({yaw} - {rest}) < 0.02", timeout=4000)

        await page.click("#menuBtn")                                  # the menu stops the looking
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.evaluate("finger('pointerdown', 380, 700)")
        await asyncio.sleep(0.6)
        assert abs(await page.evaluate(yaw) - rest) < 0.02
        await page.evaluate("finger('pointerup', 380, 700); closeSheet('drawer')")
        await page.wait_for_function("!document.documentElement.classList.contains('menu')")
        await page.evaluate("finger('pointerdown', 20, 700)")         # and after it closes, looks again (left now)
        await page.wait_for_function(f"{yaw} - {rest} < -0.15", timeout=3000)
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_menu_holds_tabs_chats_and_settings(bridge):
    """Like Muse: the menu has the tabs, the chats (with search) and settings."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        assert await page.is_hidden("#drawer")
        await page.evaluate(FAKE_CHAT)
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        assert await page.is_visible("#tabs [data-tab=upcoming]") and await page.is_visible(".conv[data-id=b]")
        assert await page.is_visible(".conv[data-id=b] .unread-dot")          # changed since last seen
        assert await page.inner_text(".conv[data-id=b] .tx") == await page.evaluate("S.convs.find(c => c.id === 'b').title")   # name only
        await page.evaluate("() => { const real = api; window.api = (path, o) => o?.method === 'PATCH' ? Promise.resolve({}) : real(path, o); }")   # fake chats
        await page.click(".conv[data-id=b] [data-rename]")
        await page.wait_for_function("$('#renameSheet').classList.contains('open')")
        assert await page.input_value("#renameForm input") == await page.evaluate("S.convs.find(c => c.id === 'b').title")
        await page.fill("#renameForm input", "Fiber plans")
        await page.click("#renameForm button[type=submit]")
        await page.wait_for_function("$('#renameSheet').hidden && $('.conv[data-id=b] .tx').textContent === 'Fiber plans'")
        await page.fill("#convSearch", "fiber")
        assert await page.eval_on_selector_all("#convList .conv", "els => els.map(e => e.dataset.id)") == ["b"]
        await page.evaluate("() => { const real = api; window.dels = []; window.api = (path, o) => o?.method === 'DELETE' ? (dels.push(path), Promise.resolve({})) : real(path, o); }")
        await page.click(".conv[data-id=b] [data-del]")                       # one tap deletes, no confirm
        assert await page.evaluate("dels") == ["/api/conversations/b"]
        await page.click("#tabs [data-tab=upcoming]")
        await page.wait_for_function("$('#drawer').hidden")                   # picking a tab closes the menu
        assert await page.is_visible("#view-upcoming") and await page.is_hidden("#view-chat")
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        assert await page.locator("#tabs [data-tab=activity]").count() == 0   # Activity lives in Settings
        await page.click("#settingsBtn")
        await page.wait_for_function("$('#drawer').hidden && $('#settings').classList.contains('open')")
        await page.click("#openActivity")
        await page.wait_for_function("$('#settings').hidden && !$('#view-activity').hidden")
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.click("#settingsBtn")
        await page.wait_for_function("$('#settings').classList.contains('open')")
        await page.click("[data-close=settings]")
        await page.wait_for_function("$('#settings').hidden")
        assert errors == []
        await b.close()


LONG_CHAT = """(running) => {
  S.convs = [{ id: 'a', title: 'Plan my week', preview: '', updated: 100, read: 100, running, source: 'app' }];
  S.current = 'a'; S.onMain = false; S.tab = 'chat';
  S.conv = { messages: Array.from({ length: 40 }, (_, i) => i % 2
    ? { role: 'assistant', text: 'Reply ' + i + ', long enough to wrap onto a second line.', tools: [], notes: [] }
    : { role: 'user', text: 'Question ' + i }) };
  if (running) S.conv.messages.push({ role: 'assistant', text: 'Working on it', tools: [], notes: [] });
  renderAll();
}"""
FRAME = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"


@pytest.mark.e2e
async def test_chat_scrolls_up_while_milo_writes(bridge):
    """A streaming reply keeps the chat at its newest line until you scroll up. Following sets scrollTop, which on iOS
    undoes a drag, so a chat that followed within 120 px of the end could not be scrolled up while Milo wrote."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(LONG_CHAT, True)
        gap = "(() => { const s = $('#chatScroll'); return Math.round(s.scrollHeight - s.scrollTop - s.clientHeight); })()"

        async def write():
            await page.evaluate("handle({ t: 'chunk', id: 'a', text: ' and more.\\n\\nA new line' })")
            await page.evaluate(FRAME)

        await write()
        await page.wait_for_function(f"{gap} < 2")                    # follows the reply (it glides there)
        for _ in range(3):                                             # a slow drag up, new text between the moves
            await page.evaluate("$('#chatScroll').scrollTop -= 20")
            await page.evaluate(FRAME)
            await write()
        assert await page.evaluate(gap) > 50                           # not pulled back to the bottom
        await page.evaluate("$('#chatScroll').scrollTop = 1e9")       # back at the end, it follows again
        await page.evaluate(FRAME)
        await write()
        await page.wait_for_function(f"{gap} < 2")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_new_chat_does_not_make_room_for_a_keyboard_that_never_came(bridge):
    """A new chat on the phone left the app shrunk to its last keyboard height for 1-2 s, with no keyboard: the
    message box sat high and the tab bar and ideas were cut off. Only a tap on the box moves the app early."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        assert not await page.evaluate("fineKeys.matches")                  # a phone: no hardware keyboard
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("Kb.h = 336; 0")                                 # a keyboard was seen before
        whole = """(() => !document.documentElement.classList.contains('kb') && !$('#tabbar').hidden
          && Math.abs($('#app').getBoundingClientRect().height - fullHeight()) < 2)()"""
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.click("#drawerNew")
        for _ in range(8):                                                   # through the drawer's slide and after
            await page.wait_for_timeout(100)
            assert await page.evaluate(whole)
        assert await page.evaluate("S.current === null && document.activeElement !== input")
        await page.click("#moreBtn")
        await page.click("[data-more=new]")
        await page.wait_for_timeout(200)
        assert await page.evaluate(whole) and await page.evaluate("document.activeElement !== input")
        await page.evaluate("input.focus()")                                 # any focus from code: wait for iOS
        await page.wait_for_timeout(100)
        assert await page.evaluate(whole)
        await page.evaluate("input.blur()")
        await page.tap("#input")                                             # a tap still moves with the keyboard
        await page.wait_for_function("document.documentElement.classList.contains('kb')", timeout=500)
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_chat_is_ready_as_settings_closes(bridge):
    """Settings and the menu slide out for 0.3 s, and taps and swipes in that time reach the chat. The keyboard for a
    Settings field leaves the chat where you were reading."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(LONG_CHAT, False)
        await page.evaluate("$('#chatScroll').scrollTop = 300")
        on_chat = """(() => { const r = $('#chatScroll').getBoundingClientRect();
          return !document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('.sheet, .drawer'); })()"""
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.click("#settingsBtn")
        await page.wait_for_function("$('#settings').classList.contains('open')")
        await page.focus("[data-set=tone]")
        await page.evaluate(FAKE_KEYBOARD, 336)
        assert await page.evaluate("$('#chatScroll').scrollTop") == 300    # no jump to the newest message
        await page.evaluate("visualViewport.height = innerHeight; fitViewport()")   # keyboard down
        await page.click("[data-close=settings]")
        assert await page.evaluate("!$('#settings').hidden") and await page.evaluate(on_chat)   # sliding out, chat on top
        await page.wait_for_function("$('#settings').hidden")
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.evaluate("closeSheet('drawer')")
        assert await page.evaluate(on_chat)
        assert errors == []
        await b.close()

AWAY_AND_BACK = """async () => {   // another app, then back to Milo
  for (const v of [false, true]) {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => v ? 'visible' : 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await new Promise((r) => setTimeout(r, 300));
  }
}"""
EDGE_SWIPE = """async ([x0, x1]) => {
  const fire = (type, x) => { const e = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(e, 'touches', { value: type === 'touchend' ? [] : [{ clientX: x, clientY: 400 }] }); document.body.dispatchEvent(e); };
  fire('touchstart', x0);
  for (let i = 1; i <= 10; i++) { await new Promise((r) => setTimeout(r, 40)); fire('touchmove', x0 + (x1 - x0) * i / 10); }
  fire('touchend', x1);
}"""


@pytest.mark.e2e
async def test_coming_back_keeps_your_place_and_the_menu_swipe_is_safe(bridge):
    """Back from another app, the chat stays where you were reading and the Library stays in its folder. An edge swipe
    under a full-screen file does not open the menu behind it, a file pulls down to close, and a menu swiped open
    again while it slides shut stays open."""
    (bridge["data"] / "lib" / "Nav").mkdir(parents=True, exist_ok=True)
    (bridge["data"] / "lib" / "Nav" / "note.txt").write_text("a note")
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(LONG_CHAT, False)
        await page.evaluate("""() => { const real = api; window.api = async (path, o) => {   // the Mac knows chat a
          if (path === '/api/conversations/a') return { ...S.conv, id: 'a', messages: [...S.conv.messages] };
          const r = await real(path, o);
          if (path === '/api/state') r.conversations.push(S.convs.find((c) => c.id === 'a'));
          return r;
        }; }""")
        await page.evaluate("$('#chatScroll').scrollTop = 300; Follow.on = false")   # read up, as a finger would
        await page.evaluate(AWAY_AND_BACK)
        await page.wait_for_timeout(300)
        assert await page.evaluate("$('#chatScroll').scrollTop") == 300          # no jump to the newest message

        await page.click("#tabbar [data-tab=library]")
        await page.click("#libSeg [data-v=all]")
        await page.click("#libraryList .item[data-dir='Nav']")
        await page.evaluate(AWAY_AND_BACK)
        await page.wait_for_timeout(300)
        assert await page.evaluate("[S.libView, S.libDir]") == ["all", "Nav"]
        assert await page.is_visible("#libraryList [data-path='Nav/note.txt']")

        await page.click("#libraryList [data-path='Nav/note.txt'] .tx")
        await page.wait_for_selector("#fileView", state="visible")
        await page.evaluate(EDGE_SWIPE, [4, 300])
        await page.wait_for_timeout(400)
        assert await page.evaluate("$('#drawer').hidden && !document.documentElement.classList.contains('menu')")
        for t, y in [("touchstart", 300), ("touchmove", 320), ("touchmove", 520), ("touchend", 0)]:
            await page.evaluate(TOUCH, ["#fvBody", t, 200, y])
        await page.wait_for_selector("#fileView", state="hidden")

        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        await page.wait_for_timeout(350)
        await page.evaluate("closeSheet('drawer')")
        await page.evaluate(EDGE_SWIPE, [4, 300])                                  # takes longer than the slide out
        await page.wait_for_timeout(400)
        assert await page.evaluate("!$('#drawer').hidden && $('#drawer').classList.contains('open')")
        assert errors == []
        await b.close()
    shutil.rmtree(bridge["data"] / "lib" / "Nav")                                  # the Library tests count folders


@pytest.mark.e2e
async def test_message_box_sits_on_the_keyboard(bridge):
    """With the keyboard up, the app fits the space above it: no gap under the message box."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.click("#input")
        await page.evaluate(FAKE_KEYBOARD, 336)
        await page.wait_for_function("!document.documentElement.classList.contains('kb-move')")   # it moves with the keyboard
        gap = await page.evaluate("visualViewport.height - $('.composer').getBoundingClientRect().bottom")
        assert 0 <= gap <= 10, gap
        assert await page.is_hidden("#tabbar")                             # tab bar hides while typing
        await page.evaluate("visualViewport.height = innerHeight; fitViewport()")   # keyboard down
        # iOS 27 Safari also shrinks innerHeight while the keyboard is up; the app must still see the keyboard
        await page.evaluate("window.innerHeight = visualViewport.height = document.documentElement.clientHeight - 330; fitViewport()")
        assert await page.evaluate("document.documentElement.classList.contains('kb')")
        await page.evaluate("window.innerHeight = visualViewport.height = document.documentElement.clientHeight; fitViewport()")
        await page.wait_for_function("!document.documentElement.classList.contains('kb') && $('#app').style.height === ''")
        assert await page.is_visible("#tabbar")
        # back in the app, iOS can report a short viewport with no keyboard: no field has focus, so the app stays whole
        await page.evaluate("input.blur(); window.innerHeight = visualViewport.height = document.documentElement.clientHeight - 330; fitViewport()")
        await page.wait_for_timeout(400)
        assert not await page.evaluate("document.documentElement.classList.contains('kb')")
        assert await page.is_visible("#tabbar")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_newest_message_stays_in_view_when_the_keyboard_opens(bridge):
    """A tap on the box moves the app early, from the last keyboard height; iOS's own report comes about 0.1 s later,
    mid-move. That second move stopped the first one's pin to the end, and the end of the chat went under the box."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(LONG_CHAT, False)
        await page.evaluate("$('#chatScroll').scrollTop = 1e9; Kb.h = 336; 0")   # at the end; a keyboard was seen before
        await page.evaluate(FRAME)
        await page.tap("#input")
        await page.wait_for_function("document.documentElement.classList.contains('kb')", timeout=500)   # the early move
        await page.wait_for_timeout(100)
        await page.evaluate(FAKE_KEYBOARD, 336)                              # iOS reports the keyboard, mid-move
        await page.wait_for_function("!document.documentElement.classList.contains('kb-move')")
        await page.wait_for_timeout(100)
        gap = await page.evaluate("(() => { const sc = $('#chatScroll'); return sc.scrollHeight - sc.scrollTop - sc.clientHeight; })()")
        assert gap < 2, gap
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_streaming_only_rebuilds_the_last_message(bridge):
    """While Milo streams, earlier messages stay as they are, and an open step list stays open."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { window.first = $('#messages').firstElementChild;
            S.convs[0].running = true;
            S.conv.messages.push({ role: 'assistant', text: '', notes: [],
                                   tools: [{ id: 't1', title: 'Search the web', status: 'in_progress' }] });
            renderMessages(); document.querySelector('details.steps').open = true; }""")
        for i in range(20):
            await page.evaluate(f"handle({{t: 'chunk', id: 'a', text: 'word{i} '}})")
        await page.wait_for_function("document.body.innerText.includes('word19')")
        assert await page.evaluate("$('#messages').firstElementChild === window.first")
        assert await page.evaluate("document.querySelector('details.steps').open")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_swipe_opens_and_closes_the_menu(bridge):
    swipe = """async ([x0, x1]) => {
      const t = (x) => new Touch({ identifier: 1, target: document.body, clientX: x, clientY: 400 });
      const fire = (type, x) => document.dispatchEvent(new TouchEvent(type,
        { touches: type === 'touchend' ? [] : [t(x)], changedTouches: [t(x)], bubbles: true }));
      fire('touchstart', x0);
      for (let i = 1; i <= 8; i++) { fire('touchmove', x0 + (x1 - x0) * i / 8); await new Promise((r) => setTimeout(r, 16)); }
      fire('touchend', x1);
    }"""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, engine="chrome")
        await page.evaluate(swipe, [5, 250])
        await page.wait_for_function("$('#drawer').classList.contains('open') && !$('#drawer').hidden")
        await page.evaluate(swipe, [300, 40])
        await page.wait_for_function("$('#drawer').hidden")
        await page.evaluate(swipe, [5, 60])                                    # too short: springs back
        await page.wait_for_timeout(450)
        assert await page.evaluate("$('#drawer').hidden")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_muse_header_tab_bar_and_more_menu(bridge):
    """Avatar in the middle (tap to talk), floating tab bar, and a "..." menu with new chat, voice, browser, settings."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        assert await page.input_value("#input") == "" and await page.get_attribute("#input", "placeholder") == "Message in Plan my week"
        await page.click("#tabbar [data-tab=library]")
        await page.wait_for_function("S.tab === 'library'")
        assert await page.is_visible("#view-library") and await page.get_attribute("#tabbar [data-tab=library]", "class") == "active"
        await page.click("#tabbar [data-tab=chat]")
        await page.click("#moreBtn")
        assert await page.is_visible("#moreMenu")
        await page.mouse.click(40, 500)                                        # tap outside closes it
        await page.wait_for_function("$('#moreMenu').hidden")
        await page.click("#moreBtn")
        await page.click("[data-more=new]")
        await page.wait_for_function("S.current === null && $('#moreMenu').hidden")
        assert await page.get_attribute("#input", "placeholder") in ("Plan my week", "Tidy Downloads")  # an idea
        await page.click("#moreBtn")
        await page.click("[data-more=settings]")
        await page.wait_for_function("$('#settings').classList.contains('open')")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_side_chat_shows_its_name_in_the_header(bridge):
    """Like Muse: a side chat has its name next to the menu button instead of the avatar; the main chat has the avatar."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)                                         # a side chat
        assert await page.is_visible("#barTitle") and await page.inner_text("#barTitleText") == "Plan my week"
        await page.wait_for_function("getComputedStyle($('#avatarBtn')).visibility === 'hidden'")   # after its fade
        await page.evaluate("() => { S.onMain = true; setTitle(); }")
        assert await page.is_hidden("#barTitle")
        await page.wait_for_selector("#avatarBtn", state="visible")
        await page.evaluate("() => { S.onMain = false; switchTab('feed'); }")    # other tabs keep the avatar
        assert await page.is_hidden("#barTitle")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_scheduled_run_is_not_shown_as_the_users_message(bridge):
    """A run of a scheduled task shows as a "<title> ran" line, not as a bubble the user seems to have typed."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push(
            { role: 'user', text: 'Run one job sweep', scheduled: true, task: 'Job sweep', ts: Date.now() / 1000 },
            { role: 'assistant', text: 'Nothing new.', tools: [], notes: [] }); renderMessages(); }""")
        assert (await page.inner_text(".msg.event")).startswith("Job sweep ran · Today")
        assert await page.locator(".msg.user").count() == 1 and "Run one job sweep" not in await page.inner_text("#messages")
        assert errors == []
        await b.close()



@pytest.mark.e2e
async def test_milos_reaction_sits_on_the_bubble_corner(bridge):
    """A reaction from the Mac shows as a small emoji on the top-left corner of the user's bubble, like a tapback."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push({ role: 'user', text: 'I passed the exam!', ts: 1000 });
            renderMessages(); handle({ t: 'reaction', id: 'a', ts: 1000, emoji: '\U0001F389' }); }""")
        chip = page.locator(".msg.user.reacted .reaction")
        assert await chip.inner_text() == "\U0001F389" and await page.locator(".reaction").count() == 1
        box, bubble = await chip.bounding_box(), await page.locator(".msg.user.reacted .bubble").bounding_box()
        assert box["x"] < bubble["x"] < box["x"] + box["width"] and box["y"] < bubble["y"] < box["y"] + box["height"]
        prev = await page.locator(".msg").nth(-2).bounding_box()                  # room above it: nothing covered
        assert prev["y"] + prev["height"] <= box["y"] + 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_a_preview_page_opens_over_the_chat_and_back_is_instant(bridge):
    """2026-10-21: a preview linked in a chat (the Reactions drafts) took the whole app to that page, and its Back
    button loaded the app again with the splash. It now opens over the app: Back closes it at once, on the same
    chat at the same place, with no reload. A page opened outside the app comes back to it without the splash."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(LONG_CHAT, False)
        await page.evaluate(f"""() => {{ S.conv.messages.push({{ role: 'assistant', tools: [], notes: [],
          text: 'Drafts: [Reactions]({BASE}/reaction-preview.html) and https://example.com' }}); renderMessages(); }}""")
        await page.evaluate("window.alive = 1; $('#chatScroll').scrollTop = 300; Follow.on = false")
        assert await page.evaluate("appPage('https://example.com/x.html')") is None    # other sites still open outside
        assert await page.evaluate("appPage('/api/library/file?path=a.html')") is None
        await page.locator("#messages a", has_text="Reactions").last.dispatch_event("click")
        await page.wait_for_function("!$('#pageView').hidden")
        frame = page.frame_locator("#pageFrame")
        await frame.locator("#back").wait_for()
        assert page.url.split("#")[0].rstrip("/") == BASE                          # the app never left
        await frame.locator("#back").click()
        await page.wait_for_function("$('#pageView').hidden")
        assert await page.evaluate("[window.alive, $('#chatScroll').scrollTop, S.current, !!$('#splash')]") == [1, 300, 'a', False]

        await page.locator("#messages a", has_text="Reactions").last.dispatch_event("click")   # the browser's back too
        await page.wait_for_function("!$('#pageView').hidden")
        await page.go_back()
        await page.wait_for_function("$('#pageView').hidden")
        assert await page.evaluate("window.alive") == 1
        assert errors == []
        await b.close()

        b = await p.webkit.launch()                                                  # outside the app: no splash back
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"])
        await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false })")
        page = await ctx.new_page()
        await page.goto(f"{BASE}/reaction-preview.html")
        await page.click("#back")
        await page.wait_for_url(f"{BASE}/")
        await page.wait_for_load_state()
        assert await page.evaluate("[!!document.getElementById('splash'), localStorage.getItem('milo-back')]") == [False, None]
        await b.close()


MAIN_CHAT = """(ts) => { S.current = 'a'; S.onMain = true; S.tab = 'chat';
  S.conv = { messages: [{ role: 'user', text: 'I passed the exam!', ts }] }; renderAll(); }"""


@pytest.mark.e2e
async def test_milos_reaction_comes_out_of_the_dog(bridge):
    """The user picked "B, Thought": a live reaction plays from the header dog. Milo looks up, a small cloud with the
    emoji sits on the rim of his circle, and the emoji lands on the message as the chip, which waits hidden until then.
    A reaction that comes with a loading chat just shows, and reduced motion skips the cloud."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.wait_for_function("Ava.dog")
        await page.evaluate(MAIN_CHAT, 1000)
        turn = "Ava.dog.parts.head.rotation.y"
        before = await page.evaluate(turn)
        await page.evaluate("handle({ t: 'reaction', id: 'a', ts: 1000, emoji: '\U0001F389' })")
        chip = page.locator(".msg.user.reacted .reaction")
        assert await chip.get_attribute("class") == "reaction later" and not await chip.is_visible()
        await page.wait_for_timeout(1300)
        cloud, face = await page.locator(".rx .cloud").bounding_box(), await page.locator(".avatar-face").bounding_box()
        assert await page.locator(".rx .emoji").inner_text() == "\U0001F389"
        dx = cloud["x"] + cloud["width"] / 2 - (face["x"] + face["width"] / 2)
        dy = cloud["y"] + cloud["height"] / 2 - (face["y"] + face["height"] / 2)
        assert dx > 0 and dy < 0 and 25 < (dx * dx + dy * dy) ** 0.5 < 45                     # on the rim, half in
        assert await page.evaluate(turn) > before + 0.1                                        # looks up at it
        await page.wait_for_function("!document.querySelector('.rx')", timeout=6000)
        assert await chip.get_attribute("class") == "reaction" and await chip.is_visible()
        # with a chat that loads, reactions it missed only show
        await page.evaluate("handle({ t: 'reaction', id: 'a', ts: 1000, emoji: '\u2764\ufe0f' }, true)")
        assert await chip.inner_text() == "❤️" and await page.locator(".rx").count() == 0
        assert errors == []
        await b.close()
        b, page, errors = await phone_page(p, reduced_motion="reduce")
        await page.wait_for_function("Ava.dog")
        await page.evaluate(MAIN_CHAT, 1000)
        await page.evaluate("handle({ t: 'reaction', id: 'a', ts: 1000, emoji: '\U0001F389' })")
        chip = page.locator(".msg.user.reacted .reaction")
        assert await page.locator(".rx").count() == 0 and await chip.get_attribute("class") == "reaction"
        assert errors == []
        await b.close()

@pytest.mark.e2e
async def test_tap_a_task_to_see_its_runs(bridge):
    """Tapping a task in Upcoming shows each run with its result. A run has no chat to open: its message, if any, is in
    the main chat."""
    item = httpx.post(f"{BASE}/api/schedules", headers=H,
                      json={"text": "Run a sweep", "kind": "task", "cron": "*/30 * * * *"}).json()
    runs = [{"id": "r2", "ts": time.time(), "status": "quiet", "conv": "a", "summary": "Sweep complete - nothing new."},
            {"id": "r1", "ts": time.time() - 1800, "status": "error", "conv": "a",
             "summary": "You've hit your session limit"}]
    try:
        async with async_playwright() as p:
            b, page, errors = await phone_page(p)
            await page.evaluate("""([runs]) => { const real = api; window.opened = [];
                window.api = (path, o) => path.endsWith('/history') ? Promise.resolve(runs) : real(path, o);
                window.openConv = (id) => opened.push(id); switchTab('upcoming'); }""", [runs])
            await page.click(f".item.sched[data-sid='{item['id']}'] .tx")
            await page.wait_for_function("$('#taskSheet').classList.contains('open') && document.querySelectorAll('.run').length === 2")
            assert await page.inner_text("#taskSheetTitle") == "Run a sweep"
            assert await page.inner_text(".task-info span") == "Every 30 minutes"
            assert await page.inner_text(".run.quiet b") == "Nothing new" and "session limit" in await page.inner_text(".run.error p")
            await page.click(".run.quiet")
            await page.wait_for_timeout(300)
            assert await page.evaluate("opened") == [] and await page.evaluate("S.tab") == "upcoming"
            assert await page.locator("#taskSheet [data-conv]").count() == 0          # no "Open chat" either
            assert errors == []
            await b.close()
    finally:
        httpx.delete(f"{BASE}/api/schedules/{item['id']}", headers=H)


@pytest.mark.e2e
async def test_upcoming_has_only_tasks(bridge):
    """Reminders are gone (to-dos live in Tasks.md): the New form makes a task with no Reminder choice, a row shows no
    kind chip, the empty state does not offer reminders, and an old reminder message in a chat has no "Reminder" label."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push({ role: 'assistant', text: 'Weight?', reminder: true, ts: 1 });
          renderMessages(); }""")
        assert await page.locator(".msg.assistant .meta").count() == 0
        assert "Reminder" not in await page.inner_text("#messages")
        await page.click("#tabbar [data-tab=upcoming]")
        await page.wait_for_function("S.schedules")
        empty = await page.inner_text("#scheduleList")
        assert "remind" not in empty.lower() and "Nothing scheduled" in empty
        assert "Reminder" not in await page.inner_text("#view-upcoming .view-sub")
        await page.click("#addScheduleBtn")
        await page.wait_for_function("!$('#scheduleSheet').hidden")
        assert await page.locator("#kindSeg").count() == 0 and "Reminder" not in await page.inner_text("#scheduleSheet")
        await page.fill("#scheduleForm textarea", "Summarize my week")
        await page.select_option("#scheduleForm select[name=repeat]", "daily")
        await page.fill("#scheduleForm input[name=time]", "14:30")
        await page.click("#scheduleForm button[type=submit]")
        await page.wait_for_function("$('#scheduleList .item')")
        [item] = [i for i in httpx.get(f"{BASE}/api/schedules", headers=H).json() if i["text"] == "Summarize my week"]
        try:
            assert (item["kind"], item["cron"]) == ("task", "30 14 * * *")
            assert await page.locator(f"[data-sid='{item['id']}'] .chip").count() == 0
            assert (await page.inner_text(f"[data-sid='{item['id']}'] .tx > span")).startswith("Every day at 2:30 PM")
            assert errors == []
        finally:
            httpx.delete(f"{BASE}/api/schedules/{item['id']}", headers=H)
            await b.close()


@pytest.mark.e2e
async def test_upcoming_splits_active_and_inactive(bridge):
    """Upcoming has Active (switched on) and Inactive (paused or done). The switch moves an item across;
    the chosen sub-tab is kept across a reload."""
    on = httpx.post(f"{BASE}/api/schedules", headers=H, json={"text": "Water plants", "cron": "0 9 * * *"}).json()
    off = httpx.post(f"{BASE}/api/schedules", headers=H, json={"text": "Call mom", "when": "2099-01-01T10:00"}).json()
    httpx.patch(f"{BASE}/api/schedules/{off['id']}", headers=H, json={"enabled": False})
    done = {"id": "done-1", "title": "Pay rent", "text": "Pay rent", "kind": "task", "cron": None, "next": None,
            "enabled": False, "last_run": time.time() - 3600, "runs": 1}
    ids = "els => els.map(e => e.dataset.sid).filter(id => [%r, %r, 'done-1'].includes(id))" % (on["id"], off["id"])
    # the Mac's list plus one finished one-time task (one-time items are done only after they fire)
    patch = """([done]) => { const real = api;
        window.api = (path, o) => path === '/api/schedules' && !o ? real(path, o).then((l) => [...l, done]) : real(path, o); }"""
    try:
        async with async_playwright() as p:
            b, page, errors = await phone_page(p)
            await page.evaluate(patch, [done])
            await page.click("#tabbar [data-tab=upcoming]")
            await page.wait_for_function("$('#scheduleList .item')")
            assert await page.inner_text("#upSeg .on") == "Active"                     # opens on Active
            assert await page.eval_on_selector_all("#scheduleList [data-sid]", ids) == [on["id"]]
            await page.click("#upSeg [data-v=inactive]")
            assert sorted(await page.eval_on_selector_all("#scheduleList [data-sid]", ids)) == sorted([off["id"], "done-1"])
            assert "Done" in await page.inner_text("[data-sid='done-1'] .tx > span")
            assert "Paused" in await page.inner_text(f"[data-sid='{off['id']}'] .tx > span")
            await page.click(f"[data-sid='{off['id']}'] [data-toggle]")                # resume: moves to Active
            await page.wait_for_function(f"!$(\"[data-sid='{off['id']}']\")")
            assert next(i for i in httpx.get(f"{BASE}/api/schedules", headers=H).json() if i["id"] == off["id"])["enabled"]
            await page.click("#upSeg [data-v=active]")
            assert sorted(await page.eval_on_selector_all("#scheduleList [data-sid]", ids)) == sorted([on["id"], off["id"]])
            await page.click(f"[data-sid='{on['id']}'] [data-toggle]")                 # pause: moves to Inactive
            await page.wait_for_function(f"!$(\"[data-sid='{on['id']}']\")")
            await page.click("#upSeg [data-v=inactive]")
            assert await page.eval_on_selector_all("#scheduleList [data-sid]", ids) == [on["id"], "done-1"]
            assert await page.is_visible(f"[data-sid='{on['id']}'] .switch:not(.on)")
            await page.reload()                                                       # the sub-tab is kept
            await page.wait_for_function("S.wsOpen")
            await page.evaluate(patch, [done])
            await page.evaluate("switchTab('upcoming'); loadUpcoming()")
            await page.wait_for_function("$(\"[data-sid='done-1']\")")
            assert await page.inner_text("#upSeg .on") == "Inactive"
            assert await page.eval_on_selector_all("#scheduleList [data-sid]", ids) == [on["id"], "done-1"]
            assert errors == []
            await b.close()
    finally:
        for i in (on, off):
            httpx.delete(f"{BASE}/api/schedules/{i['id']}", headers=H)


@pytest.mark.e2e
async def test_settings_show_claude_usage(bridge):
    """Settings shows what is left of each Claude limit, when it resets, and Claude Code's notes."""
    usage = {"plan": "Pro", "email": "me@example.com",
             "limits": [{"label": "This session", "used": 92, "resets": None, "resets_text": "Oct 18 at 3:09am"},
                        {"label": "This week (all models)", "used": 44, "resets": "2099-01-05T03:00:00-05:00",
                         "resets_text": "Jan 5 at 3am"}],
             "notes": [{"title": "Last 24h · 613 requests · 22 sessions", "lines": ["Top MCP servers: milo-browser 44%"]},
                       {"title": "Last 7d · 613 requests · 22 sessions", "lines": ["Top MCP servers: milo-browser 44%"]}]}
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""([usage]) => { const real = api;
            window.api = (path, o) => path === '/api/usage' ? Promise.resolve(usage) : real(path, o); openSettings(); }""", [usage])
        await page.wait_for_function("document.querySelectorAll('#usageBox .limit').length === 2")
        assert await page.inner_text("#usageBox .row b") == "Pro plan"
        tops = await page.eval_on_selector_all(".limit-top", "els => els.map(e => e.innerText.replace(/\\s+/g, ' '))")
        assert tops == ["This session 8% left", "This week (all models) 56% left"]
        assert await page.eval_on_selector_all(".meter", "els => els.map(e => e.className)") == ["meter danger", "meter ok"]
        spans = await page.eval_on_selector_all(".limit .tx > span", "els => els.map(e => e.innerText)")
        assert spans[0] == "Resets Oct 18 at 3:09am" and spans[1].startswith("Resets ") and " · in " in spans[1]
        assert await page.locator("#usageBox span", has_text="milo-browser").count() == 1   # 7d repeats 24h
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_closing_the_browser_after_a_google_sign_in_goes_back_to_settings(bridge):
    """A Google sign-in (or Open browser) from Settings opens Milo's browser over Settings. Closing it shows Settings
    again where you were, with the account shown as connected, not the chat (BEHAVIOR #91)."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => { const real = api; window.gCalls = 0; window.signedIn = false;
            window.api = (path, o) => {
              if (path === '/api/google') { gCalls++; return Promise.resolve({ configured: true, client_id: 'x', redirect: '',
                accounts: [{ email: 'me@example.com', label: 'Personal', connected: signedIn }] }); }
              if (path.endsWith('/signin')) return Promise.resolve({ connected: false, where: 'milo' });
              return real(path, o); };
            openSettings(); }""")
        await page.wait_for_function("$('[data-gsignin]')")
        await page.evaluate("$('#googleBox').scrollIntoView()")
        top = await page.evaluate("$('#settingsBody').scrollTop")
        assert top > 0
        await page.click("[data-gsignin]")
        await page.wait_for_function("BV.isOpen()")
        await page.wait_for_timeout(400)                                     # past closeSheet's 0.3 s
        assert await page.evaluate("!$('#settings').hidden && $('#settings').classList.contains('open')")
        await page.evaluate("signedIn = true")                               # the sign-in finished in the browser
        calls = await page.evaluate("gCalls")
        await page.click("#bvClose")
        assert await page.evaluate("$('#bview').hidden && !$('#settings').hidden")
        # still where it was, not back at the top (other sections load async, so allow a little drift)
        assert abs(await page.evaluate("$('#settingsBody').scrollTop") - top) < 80
        await page.wait_for_function(f"gCalls > {calls} && !$('[data-gsignin]')")   # shown as connected
        await page.click("#openBrowser")                                     # the same for Open browser
        await page.wait_for_function("BV.isOpen()")
        await page.click("#bvClose")
        assert await page.evaluate("!$('#settings').hidden")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_attach_a_file_with_plus(bridge):
    """+ uploads the file to the Mac; the message carries its path and shows a file chip."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("window.sendPrompt = (text, voice) => { window.sent = text; S.conv = { messages: [{ role: 'user', text }] }; renderMessages(); return true; }; 0")
        await page.set_input_files("#fileInput", files=[{"name": "plan.txt", "mimeType": "text/plain", "buffer": b"hello"}])
        await page.wait_for_function("S.attachments[0]?.abs")
        assert await page.is_visible("#attachments .att") and await page.is_visible("#sendBtn")   # can send a file alone
        await page.fill("#input", "Summarize this")
        await page.click("#sendBtn")
        sent = await page.evaluate("window.sent")
        path = sent.split("[Attached file: ")[1].rstrip("]")
        assert sent.startswith("Summarize this\n\n") and path.endswith("Uploads/plan.txt")
        assert (bridge["data"] / "lib" / "Uploads" / "plan.txt").read_text() == "hello"
        assert await page.inner_text(".msg.user .file-chip") == "plan.txt"
        assert await page.evaluate("S.attachments.length === 0 && $('#attachments').hidden")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_paste_or_drop_a_file_attaches_it(bridge):
    """A picture pasted into the message box (Cmd+V, or Paste on iOS) or a file dropped on the chat uploads like +;
    pasted text stays text."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        paste = """([kind]) => { const dt = new DataTransfer();
          if (kind === 'text') dt.setData('text/plain', 'just words');
          else dt.items.add(new File([new Uint8Array([137, 80, 78, 71, 1, 2, 3])], 'image.png', { type: 'image/png' }));
          const e = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
          $('#input').dispatchEvent(e); return e.defaultPrevented; }"""
        assert await page.evaluate(paste, ["text"]) is False                      # the browser pastes the text itself
        assert await page.evaluate("S.attachments.length") == 0
        assert await page.evaluate(paste, ["image"]) is True
        await page.wait_for_function("S.attachments[0]?.abs")
        name = await page.evaluate("S.attachments[0].name")
        assert name.startswith("Pasted ") and name.endswith(".png")
        assert (bridge["data"] / "lib" / "Uploads" / name).read_bytes()[:4] == b"\x89PNG"
        assert await page.is_visible("#attachments .att") and await page.is_visible("#sendBtn")
        await page.evaluate("""() => { const dt = new DataTransfer();
          dt.items.add(new File(['notes'], 'dropped.txt', { type: 'text/plain' }));
          for (const t of ['dragover', 'drop']) $('#chatScroll').dispatchEvent(new DragEvent(t, { dataTransfer: dt, bubbles: true, cancelable: true })); }""")
        await page.wait_for_function("S.attachments.length === 2 && S.attachments[1].abs")
        assert await page.evaluate("S.attachments[1].name") == "dropped.txt"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_typing_shows_send_not_a_spinner(bridge):
    """Typing while dictated words are still being transcribed turns the spinner into send at once; dictated words
    alone keep the spinner until the last pass is in. A recorder that never reports its stop doesn't leave it on."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => { window.sendPrompt = (text) => { window.sent = text; return true; };
          window.transcribe = () => new Promise(() => {});   // hangs until the 20 s limit
          ptt.rec = { stop: () => new Promise(() => {}), close() {}, chunks: [] };
          ptt.active = S.dictating = true; ptt.partial = null; renderComposer(); finishPtt(); }""")
        assert await page.evaluate("S.transcribing && $('#sendBtn').classList.contains('busy')")   # empty box: spinner
        await page.fill("#input", "that will clear the ui")
        assert await page.evaluate("!$('#sendBtn').hidden && !$('#sendBtn').classList.contains('busy')")
        assert await page.get_attribute("#sendBtn", "aria-label") == "Send"
        await page.wait_for_function("!S.transcribing", timeout=5000)              # the stop event never came
        assert await page.input_value("#input") == "that will clear the ui"        # typing is not overwritten
        await page.evaluate("""() => { S.transcribing = true; S.typedWhileBusy = false; $('#input').value = 'dictated words';
          renderComposer(); }""")
        assert await page.evaluate("$('#sendBtn').classList.contains('busy')")     # dictated text: still coming in
        await page.evaluate("S.transcribing = false; S.convs = [{ id: 'r', running: true }]; S.current = 'r'; renderComposer()")
        assert await page.is_visible("#sendBtn") and await page.is_hidden("#stopBtn")   # a reply runs: send queues it
        await page.fill("#input", "")
        assert await page.is_visible("#stopBtn") and await page.is_hidden("#sendBtn")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_typing_key_by_key_never_shows_a_spinner(bridge):
    """Typing on a desktop browser (no dictation ever started) keeps send with its arrow on every key. The spinner flag
    was undefined there, and classList.toggle('busy', undefined) flips the class, so each key swapped arrow and spinner."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        page = await (await b.new_context(viewport={"width": 1440, "height": 900}, is_mobile=False, has_touch=False)).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("S.wsOpen")
        # count every moment the spinner shows, not only the moments we sample
        await page.evaluate("""() => { const btn = $('#sendBtn'); window.spun = 0;
          new MutationObserver(() => { if (btn.classList.contains('busy')) spun++; }).observe(btn, { attributes: true }); }""")
        await page.click("#input")
        typed = ""
        for ch in "hi look at this":
            await page.keyboard.type(ch)
            typed += ch
            state = await page.evaluate("""() => { const b = $('#sendBtn');
              return [b.hidden, b.classList.contains('busy'), getComputedStyle(b.querySelector('.ring')).display,
                      getComputedStyle(b.querySelector('svg')).display, b.ariaLabel, $('#micBtn').hidden]; }""")
            assert state == [False, False, "none", "block", "Send", True], (typed, state)
        assert await page.evaluate("spun") == 0
        await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        assert await page.is_hidden("#sendBtn") and await page.is_visible("#micBtn")   # empty again: the mic
        assert errors == []
        await b.close()


# A microphone and recorder for WebKit: audio chunks every timeslice, the last one and "stop" a moment after stop().
FAKE_MIC = """(() => {
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true,
    value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
  window.MediaRecorder = class { constructor() { this.state = 'inactive'; this.mimeType = 'audio/mp4'; }
    static isTypeSupported(t) { return t === 'audio/mp4'; }
    start(ms) { this.state = 'recording'; this.t = setInterval(() => this.ondataavailable?.({ data: new Blob([new Uint8Array(2000)]) }), ms); }
    stop() { clearInterval(this.t); this.state = 'inactive';
      setTimeout(() => { this.ondataavailable?.({ data: new Blob([new Uint8Array(2000)]) }); this.onstop?.(); }, 50); } };
})()"""


@pytest.mark.e2e
async def test_dictation_shows_a_spinner_until_the_words_are_in(bridge):
    """Mic, talk, Stop: the round button is a spinner while the last pass is transcribed, also when the live pass has
    already put words in the box (it almost always has by then), and turns into the send arrow with the words. Typing
    while the words come in hides the spinner and keeps what you typed. The recorder and whisper are fakes."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        # the service worker would answer /api/transcribe itself, past page.route
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"], service_workers="block")
        await ctx.add_init_script(FAKE_MIC)
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        st = {"stopped": False, "gate": asyncio.Event(), "final": 0}

        async def whisper(route):   # live passes answer at once; the pass after Stop waits for the gate (slow whisper)
            if st["stopped"]:
                st["final"] += 1
                await st["gate"].wait()
                text = "hello there Milo"
            else:
                text = "hello"
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"text": text}))
        await page.route("**/api/transcribe", whisper)
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("S.wsOpen")
        await page.evaluate("S.voiceInput = true; window.sendPrompt = (text) => { window.sent = text; return true; }")
        button = """() => { const b = $('#sendBtn');
          return { send: !b.hidden, spin: b.classList.contains('busy'), ring: getComputedStyle(b.querySelector('.ring')).display,
                   arrow: getComputedStyle(b.querySelector('svg')).display, label: b.ariaLabel, mic: !$('#micBtn').hidden,
                   text: $('#input').value }; }"""
        spinning = {"send": True, "spin": True, "ring": "block", "arrow": "none", "label": "Processing", "mic": False}

        async def record_and_stop():
            st["stopped"], st["gate"] = False, asyncio.Event()
            await page.tap("#micBtn")
            await page.wait_for_function("$('#micBtn').classList.contains('rec') && $('#sendBtn').hidden")   # recording
            await page.wait_for_function("$('#input').value === 'hello'")      # the live pass put words in the box
            st["stopped"] = True
            await page.tap("#micBtn")                                           # Stop
            await page.wait_for_function("S.transcribing")

        await record_and_stop()
        for _ in range(3):   # the spinner holds while the request is pending
            state = await page.evaluate(button)
            assert {k: state[k] for k in spinning} == spinning, state
            await asyncio.sleep(0.4)
        assert st["final"] >= 1 and await page.evaluate("S.transcribing")
        st["gate"].set()                                                        # the words come in
        await page.wait_for_function("!S.transcribing")
        assert await page.evaluate(button) == {"send": True, "spin": False, "ring": "none", "arrow": "block", "label": "Send",
                                               "mic": False, "text": "hello there Milo"}
        assert await page.evaluate("window.sent") is None                      # Stop alone doesn't send

        # typing while the words come in: send with its arrow at once, and the typing stays
        await page.fill("#input", "")
        await record_and_stop()
        assert (await page.evaluate(button))["spin"]
        await page.focus("#input")
        await page.keyboard.press("End")
        await page.keyboard.type(" ok")
        state = await page.evaluate(button)
        assert state["send"] and not state["spin"] and state["arrow"] == "block" and state["label"] == "Send", state
        st["gate"].set()
        await page.wait_for_function("!S.transcribing")
        assert await page.input_value("#input") == "hello ok"                  # not overwritten by the last pass
        assert not (await page.evaluate(button))["spin"]

        # Stop, then send tapped on the spinner: it sends once the words are in
        await page.fill("#input", "")
        await record_and_stop()
        await page.click("#sendBtn")   # as the other tests: the emulated tap gives no click with the box focused
        assert await page.evaluate("S.sendAfter && !window.sent")   # it waits for the words
        st["gate"].set()
        await page.wait_for_function("window.sent === 'hello there Milo'")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_compaction_shows_nothing(bridge):
    """Compaction is silent, like talking to a person: "compact" is an ordinary message, a compact note saved in an old
    chat shows nothing (no line, brief or pill), the "..." menu has no Compact item, and the header never says
    Compacting."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { window.calls = []; const real = api;
          window.sendPrompt = (text) => { window.sent = text; return true; };
          window.api = (path, o) => path.includes('/compact') ? (calls.push(path), Promise.resolve({})) : real(path, o); }""")
        await page.fill("#input", "Compact.")
        await page.press("#input", "Enter")
        assert await page.evaluate("window.sent") == "Compact." and await page.evaluate("calls") == []
        await page.evaluate("""() => { S.conv.messages[1].notes = [{ kind: 'compact', text: 'Compacted from 112k tokens',
          brief: 'We planned your week.', ts: 5 }]; curConv().compacting = true; renderMessages(true); setStatus(); }""")
        kinds = await page.evaluate("[...document.querySelectorAll('#messages > .msg')].map((e) => e.className.split(' ')[1])")
        assert kinds == ["user", "assistant"] and await page.locator(".notes .note").count() == 0
        assert "Compact" not in await page.inner_text("body")
        await page.click("#moreBtn")
        assert await page.locator("#moreCompact").count() == 0 and "Compact" not in await page.inner_text("#moreMenu")
        assert errors == []
        await b.close()


TAP_CHATS = {"main1": {"id": "main1", "title": "Main chat", "main": True, "updated": 300},
             "slides": {"id": "slides", "title": "Paper slides", "main": False, "updated": 200}}


async def tap_page(p, url):
    """A phone whose Mac has a main chat and a side chat ("slides"), where Milo made a slide deck."""
    b = await p.webkit.launch()
    # the worker is tested on its own below; here it would keep the reload's requests from the fake Mac
    ctx = await b.new_context(**p.devices["iPhone 15 Pro"], service_workers="block")

    async def state(route):
        r = await route.fetch()
        st = await r.json()
        st["conversations"] = [{"source": "app", "running": False, "queued": 0, "preview": "", "schedule": None, "used": 0,
                                "compacting": False, **c} for c in TAP_CHATS.values()]
        st["mainId"] = "main1"
        await route.fulfill(response=r, json=st)

    async def conv(route):
        cid = route.request.url.split("/api/conversations/")[1].split("?")[0]
        c = TAP_CHATS[cid]
        await route.fulfill(json={"source": "app", "running": False, "queued": 0, "preview": "", "schedule": None, "used": 0,
                                  "compacting": False, **c,
                                  "messages": [{"role": "assistant", "text": f"In {c['title']}", "tools": [], "notes": []}]})

    await ctx.route("**/api/state", state)
    await ctx.route(re.compile(r".*/api/conversations/(main1|slides)$"), conv)
    await ctx.add_init_script("""(() => { const t = JSON.parse(sessionStorage.getItem('test-tap') || 'null');
      if (!t) return;
      sessionStorage.removeItem('test-tap');
      const tap = { type: 'open', chat: 'slides', url: location.origin + '/#c=slides', n: t.n, at: Date.now() };
      if (t.how === 'note') caches.open('milo-open').then((c) => c.put('/__open', new Response(JSON.stringify(tap))));
      else document.addEventListener('DOMContentLoaded', () => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: tap })));
    })()""")
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(url)
    await page.wait_for_function("S.wsOpen && S.conv")
    return b, page, errors


NOTE = """([chat, n, at]) => caches.open('milo-open').then((c) => c.put('/__open', new Response(JSON.stringify(
  { type: 'open', chat, url: location.origin + '/#c=' + chat, n, at: at ?? Date.now() }))))"""


@pytest.mark.e2e
async def test_tapped_notification_opens_its_chat(bridge):
    """A tap on "your slide deck is ready" opens the chat the deck was made in, not the main chat: when iOS starts the
    app or reloads a page it put away (on the link of the chat that was open), when it brings the open app back before
    or after the service worker runs, and when the worker opens a window. #token= in the link still signs in."""
    async with async_playwright() as p:
        # started by the worker's window: the link has the chat (and a token, as a first link would)
        b, page, errors = await tap_page(p, f"{BASE}/#token={TOKEN}&c=slides")
        assert await page.evaluate("S.current") == "slides" and await page.evaluate("store.get('token')") == TOKEN
        assert "token" not in await page.evaluate("location.hash")

        # reloaded on the main chat's link (iOS put the page away, or Milo updated while away), with the Feed tab kept.
        # The worker's note (it lasts in the phone's cache; a test browser empties its cache on reload, so the note is
        # put back as the page starts), then its message while the app starts.
        for how, n in (("note", "t1"), ("message", "t1b")):
            await page.evaluate("openMain()")
            await page.wait_for_function("S.current === 'main1'")
            await page.evaluate("""([how, n]) => { clearInterval(Tap.timer); keepView();
              sessionStorage.setItem('view', JSON.stringify({ tab: 'feed', y: 5, lib: ['today', ''] }));
              sessionStorage.setItem('test-tap', JSON.stringify({ how, n })); }""", [how, n])
            assert await page.evaluate("location.hash") == "#c=main1"
            await page.reload()
            await page.wait_for_function("S.wsOpen && S.conv")
            assert await page.evaluate("[S.current, S.tab, S.onMain]") == ["slides", "chat", False], how
            await page.wait_for_function("$('#chatScroll').textContent.includes('In Paper slides')", timeout=3000)

        # the open app comes back first; the worker writes its note a moment later
        await page.evaluate("openMain()")
        await page.wait_for_function("S.current === 'main1'")
        await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        await page.wait_for_timeout(700)
        await page.evaluate(NOTE, ["slides", "t2"])
        await page.wait_for_function("S.current === 'slides' && S.tab === 'chat'", timeout=3000)

        # the worker's message to the window iOS kept, from another tab with the menu open; the same tap again does not
        # take you back once you moved on
        await page.evaluate("openMain(); switchTab('library'); openSheet('drawer')")
        tap = "(n) => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: { type: 'open', chat: 'slides', url: '/#c=slides', n } }))"
        await page.evaluate(tap, "t3")
        await page.wait_for_function("S.current === 'slides' && S.tab === 'chat' && $('#drawer').hidden", timeout=3000)
        await page.evaluate("openMain()")
        await page.evaluate(NOTE, ["slides", "t3"])                     # the same tap's note
        await page.evaluate("Tap.check()")
        await page.evaluate(tap, "t3")
        await page.wait_for_timeout(300)
        assert await page.evaluate("S.current") == "main1"

        # a stale note (a tap minutes ago) is not used; a #c= link in the open window is
        await page.evaluate(NOTE, ["slides", "t4", 0])
        await page.evaluate("Tap.check()")
        await page.wait_for_timeout(300)
        assert await page.evaluate("S.current") == "main1"
        await page.evaluate("location.hash = '#c=slides'")
        await page.wait_for_function("S.current === 'slides'", timeout=3000)
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_service_worker_tap_tells_the_app_every_way(bridge):
    """sw.js on a tap: notes the chat, messages every open window and focuses one; with none, opens the chat's link."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        run = """async ([windows, opts]) => {
          opts = opts || {};
          const code = await (await fetch('/sw.js')).text(), handlers = {}, log = [];
          const clients = windows.map((w, i) => ({ ...w, postMessage: (m) => log.push(['post', i, m]),
            focus: async () => { log.push(['focus', i]); if (w.noFocus) throw new Error('not allowed'); return clients[i]; },
            navigate: async (u) => log.push(['nav', i, u]) }));
          // a cache that answers late (after a lock): the app must come up first, while the tap still lets it
          let release = () => {};
          const slow = new Promise((r) => { release = r; });
          const cacheApi = opts.slowCache ? { open: (n) => slow.then(() => { log.push(['cache']); return caches.open(n); }) } : caches;
          const self = { registration: { scope: location.origin + '/', showNotification() {} }, location,
            clients: { matchAll: async () => clients, claim() {},
              openWindow: async (u) => { log.push(['open', u]); if (opts.noOpen) throw new Error('not allowed'); return { url: u }; } },
            addEventListener: (t, f) => { handlers[t] = f; }, skipWaiting() {} };
          new Function('self', 'caches', code)(self, cacheApi);
          let done;
          handlers.notificationclick({ notification: { close() {}, data: { url: '/#c=slides', chat: 'slides' } }, waitUntil: (pr) => { done = pr; } });
          if (opts.slowCache) { await new Promise((r) => setTimeout(r, 200)); log.push(['released']); release(); }
          await done;
          const r = await caches.match('/__open', { cacheName: 'milo-open' });
          return { log, note: r && await r.json() };
        }"""
        link = f"{BASE}/#c=slides"
        main = lambda **w: {"focused": False, "visibilityState": "hidden", "url": f"{BASE}/#c=main1", **w}
        # the window iOS brings back is on another chat: focus alone would leave it there, so it goes to the chat's link
        out = await page.evaluate(run, [[main(), main(visibilityState="visible")], None])
        posts = [e for e in out["log"] if e[0] == "post"]
        assert [e[1] for e in posts] == [0, 1] and all(e[2]["chat"] == "slides" for e in posts)
        assert out["note"]["chat"] == "slides" and out["note"]["n"] == posts[0][2]["n"]
        assert out["log"][-2:] == [["focus", 1], ["nav", 1, link]] and not any(e[0] == "open" for e in out["log"])
        # Test E: the window iOS lists can't be focused (frozen or gone). The app must still open, on the chat's link.
        out = await page.evaluate(run, [[main(visibilityState="visible", noFocus=True)], None])
        assert ["focus", 0] in out["log"] and ["open", link] in out["log"], out["log"]
        assert not any(e[0] == "nav" for e in out["log"])               # the new window is already on the chat
        # focus and openWindow both refused (the tap's moment is over): navigate needs no tap, so it is still tried
        out = await page.evaluate(run, [[main(noFocus=True)], {"noOpen": True}])
        assert out["log"][-1] == ["nav", 0, link]
        # a slow cache after a lock does not hold the app back: it is focused before the note is written
        out = await page.evaluate(run, [[main(visibilityState="visible")], {"slowCache": True}])
        names = [e[0] for e in out["log"]]
        assert names.index("focus") < names.index("released") < names.index("cache"), out["log"]
        assert out["note"]["chat"] == "slides"                           # the note is still kept
        # a Library file opened in its own window is not the app: the app's page is brought back
        out = await page.evaluate(run, [[{"focused": True, "visibilityState": "visible", "url": f"{BASE}/api/library/file?path=a.pdf"},
                                          main()], None])
        assert ["focus", 1] in out["log"] and ["focus", 0] not in out["log"]
        out = await page.evaluate(run, [[{"focused": True, "visibilityState": "visible", "url": link}], None])
        assert not any(e[0] in ("nav", "open") for e in out["log"])     # already on it: no navigation
        out = await page.evaluate(run, [[], None])
        assert out["log"] == [["open", link]]
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_tapped_notification_opens_its_chat_when_the_network_comes_back_late(bridge):
    """iOS brings the app back (or starts it) before its network (Tailscale) is up again, so the first load of the
    tapped chat fails. A task's chat was never opened in this launch, so there is no copy in memory:
    the tap must still open it once the Mac answers, not leave you on the Main chat."""
    async with async_playwright() as p:
        b, page, errors = await tap_page(p, f"{BASE}/#token={TOKEN}")
        assert await page.evaluate("S.current") == "main1"
        assert await page.evaluate("Chats.has('slides')") is False      # never opened in this launch
        down = {"on": True, "failed": 0}

        async def flaky(route):
            if down["on"]:
                down["failed"] += 1
                return await route.abort("internetdisconnected")
            await route.fallback()

        await page.route(re.compile(r".*/api/(state|conversations/slides)$"), flaky)
        # back from the background: the worker's note is there, the network is not (yet)
        await page.evaluate(NOTE, ["slides", "net1"])
        await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        await page.wait_for_function("Tap.seen.has('net1')", timeout=3000)
        await page.wait_for_timeout(500)
        assert down["failed"] >= 1
        down["on"] = False                                                  # Tailscale is up again
        try:
            await page.wait_for_function("S.current === 'slides' && S.tab === 'chat'", timeout=6000)
        except Exception:
            pytest.fail(f"tap lost: still on {await page.evaluate('S.current')!r} after the network came back")
        await b.close()

@pytest.mark.e2e
async def test_tap_after_a_lock_opens_its_chat_and_reconnects(bridge):
    """The phone locks with Milo open on the Main chat; a task's result ("Test A") comes in its own chat and the user taps it.
    iOS thaws the page as it was, with no visibilitychange (it never counted as hidden) and a socket that died silently.
    The app must notice it slept (its clock stalled), open the tapped chat and connect again at once."""
    async with async_playwright() as p:
        b, page, errors = await tap_page(p, f"{BASE}/#token={TOKEN}")
        assert await page.evaluate("S.current") == "main1"
        await page.evaluate(NOTE, ["slides", "lock1"])
        # the clock jumped (the page was frozen) and the socket has been silent since before the lock
        await page.evaluate("window.oldWs = S.ws; S.heard = Date.now() - 120000; resumed.tick = Date.now() - 120000")
        try:
            await page.wait_for_function("S.current === 'slides' && S.tab === 'chat'", timeout=4000)
        except Exception:
            pytest.fail(f"tap lost after a lock: still on {await page.evaluate('S.current')!r}")
        await page.wait_for_function("S.ws !== window.oldWs && S.wsOpen", timeout=4000)   # a new socket, not a 4 s wait
        await page.wait_for_function("$('#chatScroll').textContent.includes('In Paper slides')", timeout=3000)
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_read_state_is_shared_across_devices(bridge):
    """Read is kept on the Mac, not per device: a chat read on the phone loses its dot on the laptop at once, after a
    reload and on a device that never opened Milo. Old chats count as read. Each device kept its own copy, so the
    laptop showed every chat the phone had read as unread (BEHAVIOR #92)."""
    dot = "$('.conv[data-id=shared] .unread-dot') !== null"
    async with async_playwright() as p:
        b, phone, errors = await phone_page(p)
        laptop_ctx = await b.new_context(viewport={"width": 1280, "height": 800})   # its own storage: another device
        laptop = await laptop_ctx.new_page()
        laptop.on("pageerror", lambda e: errors.append(str(e)))
        await laptop.goto(f"{BASE}/#token={TOKEN}")
        await laptop.wait_for_function("S.wsOpen")
        for page in (phone, laptop):
            await page.wait_for_function("S.convs.some((c) => c.id === 'shared')")
            assert await page.evaluate(dot)                                        # a new reply since it was read
            assert await page.evaluate("$('.conv[data-id=legacy]') && !$('.conv[data-id=legacy] .unread-dot')")   # migrated: read
        await phone.evaluate("openConv('shared')")
        await phone.wait_for_function("S.current === 'shared'")
        await laptop.wait_for_function(f"!({dot})", timeout=5000)                 # the Mac told the laptop
        await phone.evaluate("openMain()")
        assert not await phone.evaluate(dot)
        st = await api("GET", "/api/state")
        shared = next(c for c in st["conversations"] if c["id"] == "shared")
        assert shared["read"] == shared["updated"]
        await laptop.reload()
        await laptop.wait_for_function("S.wsOpen && S.convs.some((c) => c.id === 'shared')")
        assert not await laptop.evaluate(dot)
        fresh = await (await b.new_context(**p.devices["iPhone 15 Pro"])).new_page()   # a device with nothing stored
        await fresh.goto(f"{BASE}/#token={TOKEN}")
        await fresh.wait_for_function("S.wsOpen && S.convs.some((c) => c.id === 'shared')")
        assert not await fresh.evaluate(dot)
        # a window that missed the event (a desktop tab that never hid) takes the read state again on focus
        await laptop.evaluate("S.convs.find((c) => c.id === 'shared').read = 0; renderDrawer(); refreshList.at = 0")
        assert await laptop.evaluate(dot)
        await laptop.evaluate("dispatchEvent(new Event('focus'))")
        await laptop.wait_for_function(f"!({dot})", timeout=5000)
        assert errors == []
        await b.close()
    for cid in ("shared", "legacy"):   # the other tests start from an empty chat list
        await api("DELETE", f"/api/conversations/{cid}")


@pytest.mark.e2e
async def test_only_the_browser_picture_zooms(bridge):
    """No double-tap or pinch zoom in the app; a pinch on the browser picture zooms it."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        assert "user-scalable=no" in await page.get_attribute("meta[name=viewport]", "content")
        assert await page.evaluate("getComputedStyle(document.documentElement).touchAction") == "manipulation"
        pinch = """([sel, type, scale]) => { const e = new Event(type, { bubbles: true, cancelable: true });
          Object.assign(e, { scale, clientX: 100, clientY: 200 }); $(sel).dispatchEvent(e); return e.defaultPrevented; }"""
        assert await page.evaluate(pinch, ["#chatScroll", "gesturestart", 1])            # the app does not zoom
        await page.evaluate("$('#bview').hidden = false; $('#bvImg').src = 'icon-512.png'")
        for t, scale in [("gesturestart", 1), ("gesturechange", 2), ("gestureend", 2)]:
            assert await page.evaluate(pinch, ["#bvImg", t, scale])
        assert await page.evaluate("BV.zoom") == 2 and await page.evaluate("$('#bview').classList.contains('zoomed')")
        await page.click("#bvZoom")                                                     # 2 -> 2.4
        await page.click("#bvZoom")                                                     # back to 1
        assert await page.evaluate("BV.zoom") == 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_library_opens_folders(bridge):
    """The Library opens on Today: files added today from every folder, newest added first. All files shows folders
    you tap into (like the Files app), with a path back at the top. A starred folder shows in Favorites and opens in
    All files."""
    lib = bridge["data"] / "lib"
    for rel in ("Recurring tasks/Morning weight/Morning weight.md", "Uploads/photo.txt", "notes.txt"):
        (lib / rel).parent.mkdir(parents=True, exist_ok=True)
        (lib / rel).write_text("x")
    names = "els => els.map(e => e.querySelector('.tx b').textContent)"
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.click("#tabbar [data-tab=library]")
        await page.wait_for_function("$('#libraryList .item')")
        assert await page.inner_text("#libSeg .on") == "Today"
        today = [n for n in await page.eval_on_selector_all("#libraryList [data-path]", names)
                 if n in ("notes.txt", "photo.txt", "Morning weight.md")]          # earlier tests add files too
        assert today == ["notes.txt", "photo.txt", "Morning weight.md"]
        assert await page.inner_text("#libraryList [data-path='notes.txt'] .tx span") == "Library · just now"
        await page.click("#libSeg [data-v=fav]")
        await page.wait_for_function("$('#libraryList .empty-state')")              # Favorites, none yet
        await page.click("#libSeg [data-v=all]")
        await page.wait_for_function("$('#libraryList .item')")
        assert sorted(await page.eval_on_selector_all("#libraryList .item[data-dir]", names)) == ["Recurring tasks", "Uploads"]
        assert await page.eval_on_selector_all("#libraryList [data-path]", names) == ["notes.txt"]
        assert await page.locator(".crumbs").count() == 0
        await page.click("#libraryList .item[data-dir='Recurring tasks']")
        assert await page.eval_on_selector_all(".crumbs button, .crumbs b", "els => els.map(e => e.textContent)") == [
            "Library", "Recurring tasks"]
        assert await page.inner_text("#libraryList .item[data-dir] .tx span") == "1 file · just now"
        await page.click("#libraryList .item[data-dir='Recurring tasks/Morning weight']")
        assert await page.eval_on_selector_all("#libraryList [data-path]", names) == ["Morning weight.md"]
        await page.click(".crumbs [data-dir='Recurring tasks']")                     # one level up
        assert await page.eval_on_selector_all("#libraryList .item[data-dir]", names) == ["Morning weight"]
        await page.click(".crumbs [data-dir='']")
        assert await page.locator(".crumbs").count() == 0
        await page.click("#libraryList .item[data-dir='Uploads'] [data-star]")
        await page.wait_for_function("S.libFavs?.length === 1")                      # the Mac has it
        await page.click("#libSeg [data-v=fav]")
        assert await page.eval_on_selector_all("#libraryList .item[data-dir]", names) == ["Uploads"]
        await page.click("#libraryList .item[data-dir='Uploads']")
        assert await page.inner_text("#libSeg .on") == "All files"
        assert "photo.txt" in await page.eval_on_selector_all("#libraryList [data-path]", names)   # uploads land here too
        for v in ("hidden", "visible"):   # back from another app: still in the folder you were in
            await page.evaluate(f"Object.defineProperty(document, 'visibilityState', {{value: '{v}', configurable: true}});"
                                "document.dispatchEvent(new Event('visibilitychange'))")
        await page.wait_for_timeout(800)
        assert await page.inner_text("#libSeg .on") == "All files"
        assert await page.eval_on_selector_all(".crumbs b", "els => els.map(e => e.textContent)") == ["Uploads"]
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.parametrize("desktop", [False, True])
async def test_library_download_buttons(bridge, desktop):
    """Every file and folder row has a download button: a file comes as it is, a folder as <folder>.zip. Tapping it
    doesn't open the file or the folder, on the phone and in a laptop browser."""
    lib = bridge["data"] / "lib"
    (lib / "Dl Folder").mkdir(parents=True, exist_ok=True)
    (lib / "Dl Folder" / "inside.txt").write_text("in")
    (lib / "dl-me.txt").write_text("hello")
    async with async_playwright() as p:
        if desktop:
            b = await p.webkit.launch()
            page = await (await b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)).new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"{BASE}/#token={TOKEN}")
            await page.wait_for_function("S.wsOpen")
            await page.click("#tabs [data-tab=library]")
        else:
            b, page, errors = await phone_page(p, accept_downloads=True)
            await page.click("#tabbar [data-tab=library]")
        await page.click("#libSeg [data-v=all]")
        await page.wait_for_function("$('#libraryList .item[data-dir=\"Dl Folder\"]')")
        async with page.expect_download() as dl:
            await page.click("#libraryList .item[data-dir='Dl Folder'] [data-dl]")
        d = await dl.value
        assert d.suggested_filename == "Dl Folder.zip" and Path(await d.path()).read_bytes()[:2] == b"PK"
        assert await page.locator(".crumbs").count() == 0                    # still at the top, the folder didn't open
        async with page.expect_download() as dl:
            await page.click("#libraryList [data-path='dl-me.txt'] [data-dl]")
        d = await dl.value
        assert d.suggested_filename == "dl-me.txt" and Path(await d.path()).read_text() == "hello"
        assert await page.is_hidden("#fileView")                             # the file didn't open
        assert errors == []
        await b.close()
    shutil.rmtree(lib / "Dl Folder")
    (lib / "dl-me.txt").unlink()


@pytest.mark.e2e
@pytest.mark.parametrize("share", [True, False])
async def test_library_download_stays_in_the_home_screen_app(bridge, share):
    """In the Home Screen app on iOS, a download link opens the file in iOS's viewer in place of Milo, with no way
    back. There the file is fetched and handed to the share menu (Save to Files), or saved from a blob without one;
    the app never leaves its page."""
    lib = bridge["data"] / "lib"
    (lib / "Ios Folder").mkdir(parents=True, exist_ok=True)
    (lib / "Ios Folder" / "inside.txt").write_text("in")
    (lib / "ios-doc.pdf").write_bytes(b"%PDF-1.4 hello")
    stub = """Object.defineProperty(Navigator.prototype, 'standalone', { get: () => true });
      window.__shared = [];""" + ("""
      navigator.canShare = (d) => !!d.files?.length;
      navigator.share = async (d) => { for (const f of d.files) window.__shared.push(
        { name: f.name, type: f.type, head: new Uint8Array(await f.arrayBuffer()).slice(0, 4).join(',') }); };""" if share else """
      delete Navigator.prototype.share; delete Navigator.prototype.canShare;""")
    async with async_playwright() as p:
        b = await p.webkit.launch()
        ctx = await b.new_context(**p.devices["iPhone 15 Pro"], accept_downloads=True)
        await ctx.add_init_script(stub)
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("S.wsOpen")
        url = page.url
        await page.click("#tabbar [data-tab=library]")
        await page.click("#libSeg [data-v=all]")
        await page.wait_for_function("$('#libraryList .item[data-dir=\"Ios Folder\"]')")
        pdf = "#libraryList [data-path='ios-doc.pdf'] [data-dl]"
        folder = "#libraryList .item[data-dir='Ios Folder'] [data-dl]"
        if share:
            await page.click(pdf)
            await page.wait_for_function("window.__shared.length === 1")
            await page.click(folder)
            await page.wait_for_function("window.__shared.length === 2")
            assert await page.evaluate("window.__shared") == [
                {"name": "ios-doc.pdf", "type": "application/pdf", "head": "37,80,68,70"},     # %PDF, its own type
                {"name": "Ios Folder.zip", "type": "application/zip", "head": "80,75,3,4"}]    # PK
        else:
            async with page.expect_download() as dl:
                await page.click(pdf)
            d = await dl.value
            assert d.suggested_filename == "ios-doc.pdf" and Path(await d.path()).read_bytes() == b"%PDF-1.4 hello"
            async with page.expect_download() as dl:
                await page.click(folder)
            d = await dl.value
            assert d.suggested_filename == "Ios Folder.zip" and Path(await d.path()).read_bytes()[:2] == b"PK"
        assert page.url == url and len(ctx.pages) == 1                      # Milo stayed, nothing opened over it
        assert await page.is_hidden("#fileView") and await page.locator(".crumbs").count() == 0
        assert errors == []
        await b.close()
    shutil.rmtree(lib / "Ios Folder")
    (lib / "ios-doc.pdf").unlink()


@pytest.mark.e2e
async def test_task_messages_come_to_the_main_chat(bridge):
    """A scheduled task works in a hidden chat: the menu has no Recurring tasks folder and no dot for it. Its message
    comes to the main chat as Milo's own bubble (no "ran" line, no steps), and its approval cards ask there."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(MAIN_CHAT, 1000)
        await page.evaluate("""() => {
          S.mainId = 'a';
          S.convs = [{ id: 'a', title: 'Main chat', main: true, updated: 100, read: 100, running: false, source: 'app' },
                     { id: 'b', title: 'Diet', updated: 200, read: 200, running: false, source: 'app' },
                     { id: 'r', title: 'Email check', updated: 300, read: 100, running: false, source: 'scheduled', schedule: 's1' }];
          renderAll();
        }""")
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        assert await page.eval_on_selector_all("#convList > *", "els => els.map(e => e.dataset.id)") == ["b"]
        assert await page.locator(".folder-head").count() == 0 and "Recurring" not in await page.inner_text("#convList")
        assert await page.is_hidden(".menu-dot")                                  # the hidden chat's run is no news
        await page.evaluate("closeSheet('drawer')")
        await page.wait_for_function("$('#drawer').hidden")
        post = {"role": "assistant", "text": "Dr. Wren wrote back about the paper.", "tools": [], "notes": [], "ts": 2000,
                "from_task": "Email check"}
        await page.evaluate("(m) => handle({ t: 'message', id: 'a', message: m })", post)
        await page.evaluate("(m) => handle({ t: 'message', id: 'a', message: m })", post)   # a replay adds nothing
        kinds = await page.evaluate("[...document.querySelectorAll('#messages > .msg')].map((e) => e.className.split(' ')[1])")
        assert kinds == ["user", "assistant"] and await page.locator(".msg.event, .steps").count() == 0
        assert await page.inner_text(".msg.assistant .bubble") == "Dr. Wren wrote back about the paper."
        await page.evaluate("""handle({ t: 'approval', approval: { id: 'ap1', conv: 'r', ts: 1, title: 'Upload resume.pdf?',
          command: 'browser_file_upload resume.pdf', options: ['allow_once', 'reject_once'] } })""")
        await page.wait_for_selector("#messages .approval[data-aid=ap1]")         # asks in the main chat
        assert await page.is_hidden("#approvalBanner")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_typing_into_milos_browser_can_delete(bridge):
    """The hidden keyboard field keeps one invisible character, so Backspace works even with nothing typed (iOS)."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("window.sent = []; BV.send = (m) => sent.push(m); $('#bview').hidden = false; $('#bvKeys').onclick()")
        await page.keyboard.press("Backspace")                                    # nothing typed yet
        await page.keyboard.type("hi")
        await page.keyboard.press("Backspace")
        bs, text = {"type": "key", "key": "Backspace"}, lambda t: {"type": "text", "text": t}
        assert await page.evaluate("sent") == [bs, text("h"), text("i"), bs]
        assert await page.input_value("#bvInput") == "​"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_suggestion_in_the_message_box(bridge):
    """A gray hint in the empty box: an idea in an empty chat, Milo's <suggest> after a reply. The first space takes it."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.wait_for_function("$('#input').classList.contains('ghost')")
        assert await page.get_attribute("#input", "placeholder") == "Plan my week"
        color = await page.evaluate("getComputedStyle($('#input'), '::placeholder').color")
        assert color in ("rgb(168, 164, 155)", "rgb(124, 122, 115)"), color      # warm gray (--faint)
        await page.focus("#input")
        await page.keyboard.press("Space")
        assert await page.input_value("#input") == "Plan my week"
        await page.keyboard.press("Space")                                        # later spaces type as usual
        assert await page.input_value("#input") == "Plan my week "
        await page.fill("#input", "")
        await page.evaluate(FAKE_CHAT)                                            # an older reply, no suggestion
        assert await page.get_attribute("#input", "placeholder") == "Message in Plan my week"
        assert not await page.evaluate("$('#input').classList.contains('ghost')")
        await page.evaluate("S.conv.messages.at(-1).suggest = 'Add it to my calendar'; renderComposer()")
        assert await page.get_attribute("#input", "placeholder") == "Add it to my calendar"
        one_line = await page.evaluate("$('#input').offsetHeight")
        long = "Draft the repair request email to my landlord about the leak"     # too wide for a phone
        await page.evaluate(f"S.conv.messages.at(-1).suggest = '{long}'; renderComposer()")
        shown = await page.get_attribute("#input", "placeholder")
        assert long.startswith(shown) and len(shown) < len(long), shown           # whole words that fit
        assert await page.evaluate("$('#input').offsetHeight") == one_line
        await page.evaluate("S.conv.messages.at(-1).suggest = 'Add it to my calendar'; renderComposer()")
        await page.focus("#input")
        await page.keyboard.type(" ")
        assert await page.input_value("#input") == "Add it to my calendar"
        assert await page.evaluate("stripDirectives('Done. <sugg')") == "Done. "
        assert await page.evaluate("stripDirectives('Nothing new. <quiet/>')") == "Nothing new. "
        assert await page.evaluate("stripDirectives('Nothing new. <quie')") == "Nothing new. "
        assert await page.evaluate("stripDirectives('Hi <suggest>Book it</suggest> <goal add=x>y</goal>')") == "Hi  "
        assert await page.evaluate("stripDirectives('<say>Free after 4.</say> Detail')") == "Free after 4. Detail"
        assert await page.evaluate("stripDirectives('<say>Free after 4.</sa')") == "Free after 4."
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_tab_takes_the_suggestion_on_a_desktop(bridge):
    """On a laptop, Tab in the empty box takes the suggestion and keeps the focus there; a small "Tab" key shows beside
    it. With no suggestion, with text typed, or with Shift, Tab moves on as usual. The phone shows no Tab key."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        page = await (await b.new_context(viewport={"width": 1440, "height": 900}, is_mobile=False, has_touch=False)).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("S.wsOpen")
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("S.conv.messages.at(-1).suggest = 'Add it to my calendar'; renderComposer()")
        assert await page.is_visible("#tabHint")
        assert await page.get_attribute("#input", "placeholder") == "Add it to my calendar"
        await page.focus("#input")
        await page.keyboard.press("Tab")
        assert await page.input_value("#input") == "Add it to my calendar"
        assert await page.evaluate("document.activeElement.id") == "input"
        assert await page.evaluate("[$('#input').selectionStart, $('#input').selectionEnd]") == [21, 21]
        assert await page.is_hidden("#tabHint") and await page.is_visible("#sendBtn")
        await page.keyboard.press("Tab")                                          # text in the box: Tab moves on
        assert await page.input_value("#input") == "Add it to my calendar"
        assert await page.evaluate("document.activeElement.id") != "input"
        await page.fill("#input", "")
        await page.focus("#input")
        await page.keyboard.press("Shift+Tab")                                    # Shift+Tab never takes it
        assert await page.input_value("#input") == ""
        assert await page.evaluate("document.activeElement.id") != "input"
        await page.evaluate("S.conv.messages.at(-1).suggest = ''; renderComposer()")
        assert await page.is_hidden("#tabHint")
        await page.focus("#input")
        await page.keyboard.press("Tab")                                          # no suggestion: Tab moves on
        assert await page.input_value("#input") == ""
        assert await page.evaluate("document.activeElement.id") != "input"
        assert errors == []
        await b.close()
        b, phone, errors = await phone_page(p)                                    # the phone: no Tab key shown
        await phone.evaluate(FAKE_CHAT)
        await phone.evaluate("S.conv.messages.at(-1).suggest = 'Add it to my calendar'; renderComposer()")
        assert await phone.get_attribute("#input", "placeholder") == "Add it to my calendar"
        assert await phone.is_hidden("#tabHint")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_main_chat_and_side_chats(bridge):
    """Like Muse: the app opens on the main chat; New chat starts a side chat; the menu lists side chats only."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        assert await page.evaluate("S.onMain && S.current === null")
        await page.evaluate("S.convs = S.convs.filter((c) => c.main); 0")   # only the chats made here
        await page.evaluate("window.send = (m) => { window.sent = m; return true; }; 0")
        await page.fill("#input", "hello main")
        await page.press("#input", "Enter")
        assert (await page.evaluate("window.sent"))["id"] == "main"            # the server makes the main chat
        await page.evaluate("""() => { handle({ t: 'conv', conv: { id: 'm1', title: 'Main chat', main: true, updated: 1, preview: '' } });
            handle({ t: 'bound', ref: S.pendingRef, id: 'm1' });
            handle({ t: 'conv', conv: { id: 's1', title: 'Trip ideas', updated: 2, preview: 'Lisbon' } }); }""")
        assert await page.evaluate("S.mainId === 'm1' && S.current === 'm1'")
        await page.click("#moreBtn")
        await page.click("[data-more=new]")
        assert await page.evaluate("!S.onMain && S.current === null")
        await page.fill("#input", "hello side")
        await page.press("#input", "Enter")
        assert (await page.evaluate("window.sent"))["id"] is None             # a new side chat
        await page.click("#menuBtn")
        await page.wait_for_function("$('#drawer').classList.contains('open')")
        assert await page.eval_on_selector_all("#convList .conv", "els => els.map(e => e.dataset.id)") == ["s1"]
        await page.evaluate("window.openConv = (id) => { S.current = id; S.onMain = id === S.mainId; renderAll(); }; 0")
        await page.click("#tabs [data-main]")
        await page.wait_for_function("S.onMain && S.current === 'm1' && $('#drawer').hidden")
        assert errors == []
        await b.close()


LAYOUT = """() => ({ drawer: getComputedStyle($('#drawer')).display !== 'none', side: $('.drawer-panel').getBoundingClientRect().right,
  app: $('#app').getBoundingClientRect().left, tabbar: !!$('#tabbar').offsetWidth, menu: getComputedStyle($('#menuBtn')).visibility === 'visible',
  msgs: (({ left, right }) => [left, right])($('#messages').getBoundingClientRect()), wide: document.documentElement.scrollWidth - innerWidth })"""


@pytest.mark.e2e
async def test_desktop_browser_keeps_the_chats_in_a_sidebar(bridge):
    """In a laptop browser (900 px and up, with a mouse) the menu stays open on the left with the tabs and every chat;
    the chat or tab you pick shows on the right at a reading width, and the sidebar stays."""
    async with async_playwright() as p:
        b = await p.webkit.launch()
        page = await (await b.new_context(viewport={"width": 1440, "height": 900})).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/#token={TOKEN}")
        await page.wait_for_function("S.wsOpen")
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("() => { S.convs.unshift({ id: 'm', title: 'Main chat', main: true, updated: 300 }); S.mainId = 'm'; renderAll(); }")
        lay = await page.evaluate(LAYOUT)
        assert lay["drawer"] and lay["side"] == 300 and lay["app"] == 300   # side by side, nothing over the chat
        assert not lay["tabbar"] and not lay["menu"] and lay["wide"] <= 0
        assert lay["msgs"][1] - lay["msgs"][0] <= 720                        # a reading width, centered in the pane
        assert abs((lay["msgs"][0] + lay["msgs"][1]) / 2 - (300 + 1440) / 2) < 2
        for tab in ["chat", "feed", "goals", "library", "upcoming"]:
            assert await page.is_visible(f"#tabs [data-tab={tab}]")
        assert await page.eval_on_selector_all("#convList .conv", "els => els.map(e => e.dataset.id)") == ["a", "b"]
        assert await page.evaluate("$('.conv[data-id=a]').classList.contains('active')")
        await page.evaluate("window.openConv = (id) => { S.current = id; S.onMain = id === S.mainId; renderAll(); }; 0")
        await page.click(".conv[data-id=b]")
        await page.wait_for_function("S.current === 'b' && $('.conv[data-id=b]').classList.contains('active')")
        await page.click("#tabs [data-tab=feed]")
        await page.wait_for_function("S.tab === 'feed' && !$('#view-feed').hidden")
        assert await page.is_visible("#feedBody") and await page.is_visible("#convList .conv[data-id=a]")   # the sidebar stays
        await page.click("#tabs [data-main]")
        await page.wait_for_function("S.tab === 'chat' && S.onMain && S.current === 'm'")
        assert await page.evaluate(LAYOUT) == lay | {"msgs": (await page.evaluate(LAYOUT))["msgs"]}
        await page.fill("#convSearch", "diet")                                # typing in the sidebar search
        assert await page.eval_on_selector_all("#convList .conv", "els => els.map(e => e.dataset.id)") == ["b"]
        await page.click("#settingsBtn")
        await page.wait_for_function("$('#settings').classList.contains('open')")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_phone_layout_is_unchanged_by_the_desktop_sidebar(bridge):
    """The phone (and a big phone turned sideways, wider than 900 px) keeps the menu button, the tab bar and the
    full-width app; the menu stays shut until it is opened."""
    async with async_playwright() as p:
        for size in [None, {"width": 932, "height": 430}]:
            b, page, errors = await phone_page(p, **({"viewport": size} if size else {}))
            await page.evaluate(FAKE_CHAT)
            lay = await page.evaluate(LAYOUT)
            assert not lay["drawer"] and lay["app"] == 0 and lay["tabbar"] and lay["menu"], size
            await page.click("#menuBtn")
            await page.wait_for_function("$('#drawer').classList.contains('open')")
            await page.click(".conv[data-id=b]", trial=True)
            await page.click("#tabs [data-tab=feed]")
            await page.wait_for_function("$('#drawer').hidden && S.tab === 'feed'")   # picking a tab still closes it
            assert errors == []
            await b.close()


THEME = """() => { const cs = getComputedStyle(document.documentElement), get = (k) => cs.getPropertyValue(k).trim();
    return { theme: document.documentElement.dataset.theme || '', scheme: get('color-scheme'), saved: localStorage.getItem('theme'),
             bg: getComputedStyle(document.body).backgroundColor, dark: mmdTheme(),
             metas: [...document.querySelectorAll('meta[name=theme-color]')].map((m) => m.content),
             tokens: ['--bg', '--surface', '--surface-2', '--ink', '--muted', '--faint', '--line', '--accent', '--ok', '--warn',
                      '--danger', '--on-status', '--hl-keyword', '--x-muted', '--cloud-shadow', '--face'].map(get) }; }"""


@pytest.mark.e2e
async def test_theme_setting_system_light_or_dark(bridge):
    """Settings > Appearance > Theme: System follows the phone, Light and Dark override it on this device (localStorage),
    with the status bar color, and the saved choice is applied before the first paint. Dark picked by hand looks
    exactly like the system's dark."""
    html = (bridge["web"] / "index.html").read_text()
    assert html.index("setTheme(localStorage.getItem('theme'))") < html.index('rel="stylesheet"')   # before first paint
    light, dark = "rgb(250, 249, 245)", "rgb(38, 38, 36)"
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, color_scheme="dark")
        system_dark = await page.evaluate(THEME)
        assert system_dark["theme"] == "" and system_dark["bg"] == dark and system_dark["dark"] == "dark"
        await page.emulate_media(color_scheme="light")
        st = await page.evaluate(THEME)
        assert st["bg"] == light and st["metas"] == ["#faf9f5", "#262624"] and st["dark"] == "light"

        await page.evaluate("openSettings()")
        assert await page.eval_on_selector("#themeSel", "s => [s.value, ...[...s.options].map((o) => o.text)]") == \
            ["", "System", "Light", "Dark"]
        await page.select_option("#themeSel", "dark")   # the phone is light; Dark wins
        st = await page.evaluate(THEME)
        assert st["theme"] == "dark" and st["saved"] == "dark" and st["scheme"] == "dark" and st["bg"] == dark
        assert st["metas"] == ["#262624", "#262624"] and st["dark"] == "dark"
        assert st["tokens"] == system_dark["tokens"]   # the two dark blocks in style.css say the same

        await page.reload()
        await page.wait_for_function("S.wsOpen")
        st = await page.evaluate(THEME)
        assert st["theme"] == "dark" and st["bg"] == dark   # kept on this device

        await page.emulate_media(color_scheme="dark")
        await page.evaluate("openSettings()")
        assert await page.eval_on_selector("#themeSel", "s => s.value") == "dark"
        await page.select_option("#themeSel", "light")   # the phone is dark; Light wins
        st = await page.evaluate(THEME)
        assert st["theme"] == "light" and st["scheme"] == "light" and st["bg"] == light and st["metas"] == ["#faf9f5"] * 2

        await page.select_option("#themeSel", "")   # back to System: follows the phone again
        st = await page.evaluate(THEME)
        assert st["theme"] == "" and st["saved"] is None and st["bg"] == dark and st["metas"] == ["#faf9f5", "#262624"]
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_queued_message_waits_below_the_reply_and_drafts_stay_with_their_chat(bridge):
    """A message sent while Milo replies waits below that reply: the rest of the reply goes on above it, and the next
    reply is its own message. Stop drops the queue. What you type stays with the chat you typed it in."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        texts = "S.conv.messages.map((m) => (m.queued ? 'q:' : '') + m.text)"
        bubbles = "[...document.querySelectorAll('#messages .bubble')].map((e) => e.textContent.trim())"
        await page.evaluate("""() => {
          S.convs = [{ id: 'q', title: 'Queue', running: true, updated: 1 }]; S.current = 'q'; S.onMain = false;
          S.conv = { messages: [{ role: 'user', text: 'one', ts: 1 }] }; renderAll();
          handle({ t: 'chunk', id: 'q', text: 'a ', at: 0 });
          handle({ t: 'user', id: 'q', text: 'two', queued: true, ts: 2 });
          handle({ t: 'user', id: 'q', text: 'three', queued: true, ts: 3 });
          handle({ t: 'chunk', id: 'q', text: 'b', at: 2 }); }""")
        assert await page.evaluate(texts) == ["one", "a b", "q:two", "q:three"]
        await page.evaluate("""() => { handle({ t: 'done', id: 'q', stop: 'end_turn', queued: 2, message: { role: 'assistant', text: 'a b', tools: [], notes: [], ts: 1.5 } });
          handle({ t: 'chunk', id: 'q', text: 'c', at: 0 });
          S.conv.messages.forEach((m) => delete m.shown); renderMessages(); }""")   # revealed at once, to read the bubbles
        assert await page.evaluate(texts) == ["one", "a b", "two", "c", "q:three"]
        assert await page.evaluate(bubbles) == ["one", "a b", "two", "c", "three"]
        await page.evaluate("""() => handle({ t: 'done', id: 'q', stop: 'cancelled', queued: 0,
          message: { role: 'assistant', text: 'c', tools: [], notes: [{ kind: 'stopped' }], ts: 2.5 } })""")
        assert await page.evaluate(texts) == ["one", "a b", "two", "c", "three"]   # Stop: three won't run
        # drafts: typed in a new side chat, gone in the main chat, back in the side chat
        await page.evaluate("newChat()")
        await page.fill("#input", "for the side chat")
        await page.evaluate("openMain()")
        assert await page.input_value("#input") == ""
        await page.evaluate("newChat()")
        assert await page.input_value("#input") == "for the side chat"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_goals_screen(bridge):
    """Add goals (Goals and Tracking), tick one off, move one, delete one (two taps)."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, service_workers="block")   # WebKit routes miss what a service worker fetches
        await page.click("#tabbar [data-tab=goals]")
        await page.click("#addGoalBtn")
        await page.fill("#goalForm input[name=title]", "Run a 10k")
        await page.fill("#goalForm input[name=note]", "3 runs a week")
        await page.click("#goalForm button[type=submit]")
        await page.wait_for_selector(".goal-row")
        await page.click("#addGoalBtn")
        await page.click("#goalSeg [data-v=tracking]")
        await page.fill("#goalForm input[name=title]", "Permit case")
        await page.click("#goalForm button[type=submit]")
        await page.wait_for_function("document.querySelectorAll('.goal-row').length === 2")
        assert await page.eval_on_selector_all(".goal-section", "els => els.map(e => e.textContent)") == ["Tracking", "Goals"]
        await page.click(".goal-row:has-text('Run a 10k') [data-gtoggle]")
        await page.wait_for_selector(".goal-row.done:has-text('Run a 10k')")
        await page.click(".goal-row:has-text('Permit case') [data-gmore]")
        await page.click("[data-gact=move]")
        await page.wait_for_function("S.goals.find(g => g.title === 'Permit case').section === 'goal'")
        await page.click(".goal-row:has-text('Permit case') [data-gmore]")
        await page.dblclick("[data-gact=delete]")                                  # a double tap is one tap
        assert await page.inner_text("[data-gact=delete]") == "Tap again to delete"
        await page.wait_for_timeout(500)
        await page.click("[data-gact=delete]")
        await page.wait_for_function("S.goals.length === 1")
        goals = await api("GET", "/api/goals")
        assert [(g["title"], g["done"], g["note"]) for g in goals] == [("Run a 10k", True, "3 runs a week")]
        # Return twice on a slow Mac saves one goal
        async def slow(route):
            await asyncio.sleep(0.5)
            await route.continue_()
        await page.route("**/api/goals", slow)
        await page.click("#addGoalBtn")
        await page.fill("#goalForm input[name=title]", "Once")
        await page.press("#goalForm input[name=title]", "Enter")
        await page.press("#goalForm input[name=title]", "Enter")
        await page.wait_for_timeout(1500)
        assert [g["title"] for g in await api("GET", "/api/goals")].count("Once") == 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_ideas_screen_do_it_and_not_now(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("window.sendPrompt = (text, voice) => { window.sent = [text, S.onMain]; return true; }; 0")
        await page.click("#menuBtn")                                         # Ideas is in the menu; Feed took its tab
        await page.click("#tabs [data-tab=ideas]")
        await page.wait_for_function("document.querySelectorAll('.idea-row').length === 2")
        await page.click(".idea-row[data-idea=i-1]")
        await page.wait_for_function("$('#ideaSheet').classList.contains('open')")
        assert await page.inner_text("#ideaTitle") == "I can plan your week"
        await page.click("#ideaDo")
        await page.wait_for_function("window.sent")
        assert await page.evaluate("window.sent") == ["Plan my week", False]     # done in a new side chat
        await page.click("#menuBtn")
        await page.click("#tabs [data-tab=ideas]")
        await page.wait_for_function("document.querySelectorAll('.idea-row').length === 1")
        await page.click(".idea-row[data-idea=i-2]")
        await page.click("#ideaSkip")
        await page.wait_for_function("!document.querySelector('.idea-row')")
        assert (await api("GET", "/api/ideas"))["items"] == []
        assert errors == []
        await b.close()


def tiny_pdf(pages):
    """A small valid PDF, one line of text per page."""
    font = 3 + 2 * pages
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(pages))}] /Count {pages} >>"]
    for i in range(pages):
        text = f"BT /F1 32 Tf 72 700 Td (Page {i + 1}) Tj ET"
        objs += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>",
                 f"<< /Length {len(text)} >>\nstream\n{text}\nendstream"]
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.mark.e2e
async def test_library_files_open_in_the_app(bridge):
    """Photos, Markdown, CSV and PDF show in the app; Word comes as a Quick Look preview; share hands the file on."""
    lib = bridge["data"] / "lib" / "Viewer"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "photo.png").write_bytes(PNG_1PX)
    (lib / "notes.md").write_text("# Plan\n\n- one\n- two\n")
    (lib / "data.csv").write_text('name,score\n"Smith, J",3\n')
    (lib / "paper.pdf").write_bytes(tiny_pdf(2))
    (lib / "memo.txt").write_text("Budget memo for the lab")
    subprocess.run(["textutil", "-convert", "docx", "-output", str(lib / "memo.docx"), str(lib / "memo.txt")], check=True)
    (lib / "memo.txt").unlink()
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => { window.shared = null; Object.defineProperty(navigator, 'canShare', { value: () => true, configurable: true });
          Object.defineProperty(navigator, 'share', { value: async (d) => { window.shared = d.files.map((f) => [f.name, f.size]); }, configurable: true }); }""")
        await page.click("#tabbar [data-tab=library]")
        await page.click("#libSeg [data-v=all]")                                   # it opens on Today
        await page.click("#libraryList .item[data-dir='Viewer']")

        async def open_file(name, ready):
            await page.click(f"#libraryList [data-path='Viewer/{name}'] .tx")
            await page.wait_for_function("!$('#fileView').hidden")
            assert await page.inner_text("#fvName") == name
            await page.wait_for_function(ready, timeout=30000)

        await open_file("photo.png", "$('#fvBody img')?.naturalWidth === 1")
        await page.click("#fvClose")
        await page.wait_for_function("$('#fileView').hidden && !$('#fvBody').innerHTML")
        await open_file("notes.md", "$('#fvBody .md h2')?.textContent === 'Plan' && $$('#fvBody .md li').length === 2")
        await page.click("#fvClose")
        await open_file("data.csv", "$$('#fvBody th').length === 2")
        assert await page.eval_on_selector_all("#fvBody td", "els => els.map(e => e.textContent)") == ["Smith, J", "3"]
        await page.click("#fvShare")                                          # Open in another app
        await page.wait_for_function("window.shared")
        assert await page.evaluate("window.shared") == [["data.csv", (lib / "data.csv").stat().st_size]]
        await page.click("#fvClose")
        await open_file("paper.pdf", "$$('#fvBody .fv-page canvas').length === 2")   # PDF.js draws both pages
        assert (await page.inner_text("#fvMeta")).endswith("2 pages")
        before = await page.evaluate("$('#fvBody canvas').width")
        await page.evaluate("""() => { const el = $('#fvBody .fv-page');   // a two-finger pinch (iOS gesture events)
          for (const [type, scale] of [['gesturestart', 1], ['gesturechange', 2], ['gestureend', 2]]) {
            const e = new Event(type, { bubbles: true, cancelable: true }); e.scale = scale; el.dispatchEvent(e); } }""")
        assert await page.evaluate("FV.zoom") == 2 and await page.evaluate("$('#fvBody .fv-zoom').style.width") == "200%"
        await page.wait_for_function(f"$('#fvBody canvas').width > {before} * 1.5")   # drawn again, sharp
        await page.click("#fvClose")
        await open_file("memo.docx", "$('#fvBody iframe.fv-frame')?.getAttribute('src')?.startsWith('/preview/')")
        assert await page.get_attribute("#fvBody iframe", "sandbox") == "allow-scripts"   # away from the app's token
        await page.evaluate("document.documentElement.style.setProperty('--safe-bottom', '34px')")   # an iPhone's home bar
        assert await page.evaluate("$('#fvBody').getBoundingClientRect().bottom - $('#fvBody iframe').getBoundingClientRect().bottom") == 34
        await page.evaluate("document.documentElement.style.removeProperty('--safe-bottom')")
        for _ in range(60):
            frame = next((f for f in page.frames if "/preview/" in f.url), None)
            if frame and "Budget memo for the lab" in await frame.evaluate("document.body?.innerText || ''"):
                assert 0.5 < float(await frame.evaluate("document.documentElement.style.zoom")) < 1   # page fits the screen
                break
            await asyncio.sleep(0.25)
        else:
            raise AssertionError("the Word preview did not load")
        await page.click("#fvClose")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_feed_brief_posts_and_ask_milo(bridge):
    """Feed tab: brief lines show the posts behind them, top posts are the real tweets, Ask Milo starts a side chat."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => { window.sendPrompt = (text, voice) => { window.sent = [text, S.onMain]; return true; };
          const real = api; window.api = (path, o) => path === '/api/feed/refresh' ? (window.refreshed = true, Promise.resolve({busy: true})) : real(path, o); }""")
        assert await page.is_hidden("#tabbar [data-tab=ideas]") and await page.is_visible("#tabbar [data-tab=feed]")
        await page.click("#tabbar [data-tab=feed]")
        await page.wait_for_function("document.querySelector('.feed-brief li .feed-hl')?.textContent === 'Senate passes the budget'")
        assert await page.eval_on_selector_all("#feedSeg button", "els => els.map(e => e.textContent)") == ["Politics", "AI", "Following"]
        await page.click("#feedSeg [data-ftab=foryou]")                       # AI, from For you
        await page.wait_for_function("document.querySelectorAll('.feed-brief li').length === 2")
        assert await page.inner_text(".feed-brief li:first-child .feed-hl") == "OpenAI ships a reasoning model"   # bold headline
        assert await page.inner_text(".feed-brief li:first-child p") == "OpenAI shipped a new reasoning model."
        assert await page.inner_text(".feed-brief li:first-child .feed-src") == "2 posts"
        assert "140 posts read" in await page.inner_text(".feed-meta")
        assert await page.eval_on_selector_all(".feed-post", "els => els.map(e => e.dataset.pid)") == ["f1", "f3"]
        assert await page.query_selector(".feed-why") is None                  # no "why" box under top posts
        assert await page.get_attribute(".feed-post[data-pid=f1] a.feed-btn", "href") == "https://x.com/openai/status/f1"

        # like and dislike sit in the Open in X / Ask Milo row; a second tap takes the vote back; only stored for now
        row = await page.eval_on_selector(".feed-post[data-pid=f1] .feed-actions", """e => [e.offsetHeight,
            e.closest('.feed-post').getBoundingClientRect().right - e.lastElementChild.getBoundingClientRect().right]""")
        assert row[0] < 40 and row[1] >= 4                                    # still one line, inside the card
        size = await page.eval_on_selector(".feed-post[data-pid=f1] [data-fvote=like]", "e => [e.offsetWidth, e.offsetHeight]")
        assert size[0] >= 32 and size[1] >= 36                                # easy to hit with a thumb

        async def votes_are(want):
            for _ in range(50):
                if (await api("GET", "/api/feed"))["votes"] == want:
                    return True
                await asyncio.sleep(0.1)
        await page.click(".feed-post[data-pid=f1] [data-fvote=like]")
        assert await votes_are({"f1": "like"})
        assert await page.eval_on_selector_all(".feed-post[data-pid=f1] [data-fvote]", "els => els.map(e => e.getAttribute('aria-pressed'))") == ["true", "false"]
        await page.click(".feed-post[data-pid=f1] [data-fvote=dislike]")      # switch
        assert await votes_are({"f1": "dislike"})
        saved = json.loads((bridge["data"] / "feed_votes.json").read_text())["f1"]
        assert saved["topic"] == "AI" and saved["post"]["text"] == "We shipped a new reasoning model today."
        await page.click(".feed-post[data-pid=f1] [data-fvote=dislike]")      # take it back
        assert await votes_are({})
        assert await page.eval_on_selector_all(".feed-post[data-pid=f1] [data-fvote].on", "els => els.length") == 0

        await page.click(".feed-brief li:first-child .feed-src")             # the posts behind a line
        await page.wait_for_function("$('#feedSources').classList.contains('open')")
        # a post is not a link (a tap on its text opened X): each has its own Open in X button, in a new tab
        assert await page.eval_on_selector_all("#feedSourcesBody .feed-row", "els => els.map(e => e.tagName)") == ["DIV", "DIV"]
        assert await page.eval_on_selector_all("#feedSourcesBody .feed-row a", """els => els.map(e => [e.textContent,
            e.getAttribute('href'), e.target, e.rel])""") == [
            ["Open in X", "https://x.com/openai/status/f1", "_blank", "noopener"],
            ["Open in X", "https://x.com/researcher/status/f2", "_blank", "noopener"]]
        assert await page.eval_on_selector("#feedSourcesBody .feed-row", "e => getComputedStyle(e.querySelector('.tx')).cursor") == "auto"
        assert await page.eval_on_selector_all("#feedSourcesBody > .feed-actions .feed-btn", "els => els.map(e => e.textContent)") == [
            "Ask Milo about this"]                                            # one button per post, none down here
        tops = await page.eval_on_selector_all("#feedSourcesBody .feed-row", "els => els.map(e => getComputedStyle(e).borderTopWidth)")
        assert tops == ["0px", "1px"]                                          # no line between the story and the first post
        pages = len(b.contexts[0].pages)
        await page.click("#feedSourcesBody .feed-row:nth-of-type(2) .tx", position={"x": 20, "y": 30})   # the post's text
        await asyncio.sleep(0.5)
        assert len(b.contexts[0].pages) == pages and await page.evaluate("$('#feedSources').classList.contains('open')")
        await page.click("[data-close=feedSources]")
        await page.wait_for_function("$('#feedSources').hidden")
        await page.click(".feed-brief li:nth-child(2) .feed-src")            # one post: Open in X sits next to Ask Milo
        await page.wait_for_function("$('#feedSources').classList.contains('open')")
        assert await page.eval_on_selector_all("#feedSourcesBody .feed-row a", "els => els.length") == 0
        assert await page.eval_on_selector_all("#feedSourcesBody > .feed-actions .feed-btn", """els => els.map(e => [e.textContent,
            e.getAttribute('href'), e.target])""") == [["Open in X", "https://x.com/evalsguy/status/f3", "_blank"], ["Ask Milo about this", None, None]]
        row = await page.eval_on_selector("#feedSourcesBody > .feed-actions", """e => [e.offsetHeight,
            e.lastElementChild.getBoundingClientRect().right <= e.getBoundingClientRect().right]""")
        assert row[0] < 40 and row[1]                                         # one line at iPhone width
        await page.click("[data-close=feedSources]")
        await page.wait_for_function("$('#feedSources').hidden")

        # the For you / Following switch slides away while scrolling down and comes back on the way up
        await page.evaluate("$('#feedBody').style.paddingBottom = '2000px'; $('#feedScroll').scrollTop = 0")
        await page.wait_for_function("F.lastY === 0")                       # from the top (clicks above scrolled it)
        for y, away in ((600, True), (450, False), (900, True), (0, False)):
            await page.evaluate(f"$('#feedScroll').scrollTop = {y}")          # each scroll handled before the next
            await page.wait_for_function(f"F.lastY === {y} && $('#feedSegBar').classList.contains('away') === {str(away).lower()}")
            if y == 450:                                                      # stuck flush under the header, no gap
                await page.wait_for_timeout(350)
                assert await page.evaluate("$('#feedSegBar').getBoundingClientRect().top - $('#feedScroll').getBoundingClientRect().top") == 0
        await page.evaluate("$('#feedBody').style.paddingBottom = ''")

        await page.click(".feed-post[data-pid=f3] [data-fmore]")             # mute an account
        await page.click("[data-fact=mute]")
        await page.wait_for_function("!document.querySelector('.feed-post[data-pid=f3]')")
        assert (await api("GET", "/api/feed"))["settings"]["muted"] == ["evalsguy"]

        await page.click("#feedSeg [data-ftab=following]")
        await page.wait_for_function("document.querySelector('.feed-brief li p')?.textContent === 'A lab is hiring for safety research.'")
        await page.click("#feedSeg [data-ftab=politics]")                    # political news from For you
        await page.wait_for_function("document.querySelector('.feed-brief li .feed-hl')?.textContent === 'Senate passes the budget'")
        assert await page.eval_on_selector_all(".feed-post", "els => els.map(e => e.dataset.pid)") == ["n1"]
        await page.click(".feed-post[data-pid=n1] [data-fask]")
        await page.wait_for_function("window.sent")
        assert "what each side says" in (await page.evaluate("window.sent"))[0]
        await page.evaluate("window.sent = null")
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")

        await page.click("#feedEditBtn")                                      # a new size needs a new brief
        await page.wait_for_function("$('#feedEdit').classList.contains('open')")
        assert (await page.input_value("#feedForm [name=prompt]")).startswith("AI news and research")
        assert (await page.input_value("#feedForm [name=politics_prompt]")).startswith("Politics and world news")
        assert (await page.input_value("#feedForm [name=following_prompt]")).startswith("The key posts from people I follow")
        assert await page.get_attribute("[data-ftoggle=politics]", "aria-checked") == "true"
        await page.click("#feedTopSeg [data-v='3']")
        await page.click("#feedForm button[type=submit]")
        await page.wait_for_function("$('#feedEdit').hidden && window.refreshed")
        assert (await api("GET", "/api/feed"))["settings"]["top"] == 3

        await page.click(".feed-post[data-pid=f1] [data-fask]")
        await page.wait_for_function("window.sent")
        text, on_main = await page.evaluate("window.sent")
        assert "We shipped a new reasoning model today." in text and "https://x.com/openai/status/f1" in text and on_main is False
        assert await page.evaluate("S.tab") == "chat"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_feed_video_pauses_with_the_screen_off_and_plays_on_from_the_lock_screen(bridge):
    """A lock pauses a feed video, and so do a scroll past it and leaving the Feed. iOS pauses a video when the app hides
    but lets audio play on: bgAudio plays along, muted and in step, and the lock screen's Play goes on with it; back in
    the app the video catches up, muted, and takes the sound back. The lock screen can pause, play and seek. A video
    that plays holds back app updates. Only a tap on a video plays anything (a play() stops music in other apps).
    Playback is faked: this browser can't play X's videos or lock a screen."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => {
          const M = HTMLMediaElement.prototype;
          Object.defineProperty(M, 'paused', {get() { return !this._on; }, configurable: true});
          Object.defineProperty(M, 'readyState', {get() { return 4; }, configurable: true});
          Object.defineProperty(M, 'error', {get() { return this._err || null; }, configurable: true});   // it really loads: no errors
          Object.defineProperty(M, 'ended', {get() { return false; }, configurable: true});
          M.play = function () { this._on = true; this.dispatchEvent(new Event('play')); this.dispatchEvent(new Event('playing')); return Promise.resolve(); };
          M.pause = function () { if (this._on) { this._on = false; this.dispatchEvent(new Event('pause')); } };
          window.at = (m, t) => Object.defineProperty(m, 'currentTime', {value: t, writable: true, configurable: true});
          window.tick = (m) => m.dispatchEvent(new Event('timeupdate'));
          window.msh = {};   // the lock screen's buttons
          if (window.MediaSession) MediaSession.prototype.setActionHandler = (k, f) => { msh[k] = f; };   // (WebKit may swap the object)
          window.setHidden = (h) => {
            Object.defineProperty(document, 'visibilityState', {get: () => h ? 'hidden' : 'visible', configurable: true});
            Object.defineProperty(document, 'hidden', {get: () => h, configurable: true});
            document.dispatchEvent(new Event('visibilitychange'));
          };
        }""")
        await page.click("#tabbar [data-tab=feed]")                          # a tap outside a video plays nothing
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        assert await page.evaluate("[BG.unlocked, bgAudio.paused, player.paused]") == [False, True, True]
        # a silent clip that won't decode keeps paused false: that still isn't playing, or no update would ever go in
        await page.evaluate("bgAudio._on = true; bgAudio._err = {code: 3}")
        assert await page.evaluate("!mediaPlaying()")
        await page.evaluate("bgAudio._on = false; bgAudio._err = null")

        await page.evaluate("""() => { F.data.tabs.foryou.posts.f1.media = [{type: 'video', w: 1280, h: 720,
          url: 'https://pbs.twimg.com/amplify_video_thumb/9/img/a.jpg', video: 'https://video.twimg.com/amplify_video/9/vid/avc1/1280x720/a.mp4'}];
          renderFeed();
          window.vid = document.querySelector('.feed-post[data-pid=f1] video');
          vid.scrollIntoView({block: 'center'});
          at(vid, 12.34); at(bgAudio, 0); unlockBg({target: vid}); vid.play(); }""")   # you tap play
        assert await page.evaluate("BG.unlocked")                            # that tap lets bgAudio play sound later
        src = "https://video.twimg.com/amplify_video/9/vid/avc1/1280x720/a.mp4"
        assert await page.evaluate("[BG.v === vid, bgAudio.src, bgAudio.muted, bgAudio.paused, vid.muted]") == [
            True, src + "#t=12.34", True, False, False]                      # bgAudio comes along, muted
        if await page.evaluate("!!navigator.mediaSession && !!window.MediaMetadata"):
            assert await page.evaluate("navigator.mediaSession.metadata.artist") == "@openai"   # the lock screen shows the post
        await page.evaluate("at(bgAudio, 12.6); tick(vid)")                  # off by 0.26 s: it jumps (muted), a bit ahead
        assert await page.evaluate("bgAudio.currentTime") == pytest.approx(12.44)
        await page.evaluate("at(bgAudio, 12.3); tick(vid)")                  # the jump took longer: next time it aims further
        assert await page.evaluate("[bgAudio.currentTime, bgAudio.playbackRate]") == [12.3, 1]   # close enough; never a new speed
        assert await page.evaluate("BG.lead") == pytest.approx(0.14)

        await page.evaluate("Update.pending = true; window.stay = 1; Update.tryNow(true)")   # no update while it plays
        await page.wait_for_timeout(700)
        assert await page.evaluate("window.stay") == 1
        await page.evaluate("renderFeed()")                                  # the feed redraws: the same video plays on
        assert await page.evaluate("document.querySelector('.feed-post[data-pid=f1] video') === vid && !vid.paused")

        await page.evaluate("setHidden(true); vid.pause()")                  # the lock: it pauses (iOS pauses it too)
        assert await page.evaluate("[vid.paused, bgAudio.paused, bgAudio.muted, BG.on, BG.going, mediaPlaying()]") == [
            True, True, True, False, False, False]
        await page.evaluate("renderFeed()")                                  # a redraw keeps the paused video
        assert await page.evaluate("document.querySelector('.feed-post[data-pid=f1] video') === vid")
        await page.evaluate("msh.play ? msh.play() : (BG.going = true, takeOver())")   # Play on the lock screen
        assert await page.evaluate("[bgAudio.paused, bgAudio.muted, bgAudio.playbackRate, BG.on, mediaPlaying()]") == [
            False, False, 1, True, True]                                     # bgAudio goes on with the sound
        if await page.evaluate("!!navigator.mediaSession"):                  # the lock screen's buttons work on the sound
            await page.evaluate("Object.defineProperty(bgAudio, 'duration', {value: 120, configurable: true}); msh.seekto({seekTime: 50})")
            assert await page.evaluate("bgAudio.currentTime") == 50
            await page.evaluate("msh.seekbackward({})")
            assert await page.evaluate("bgAudio.currentTime") == 40
            await page.evaluate("msh.pause()")
            assert await page.evaluate("[bgAudio.paused, BG.going]") == [True, False]
            await page.evaluate("msh.play()")
            assert await page.evaluate("[bgAudio.paused, BG.going]") == [False, True]
        else:
            await page.evaluate("at(bgAudio, 40)")

        await page.evaluate("loadFeed = async () => {}")                    # (the Mac's feed lacks this video: no reload)
        await page.evaluate("setHidden(false)")                              # back: the picture catches up, muted
        assert await page.evaluate("[vid.paused, vid.muted, vid.currentTime, bgAudio.muted]") == [False, True, 40.3, False]
        await page.evaluate("at(vid, 40.5); at(bgAudio, 40.3); tick(vid)")   # 0.2 s ahead: it jumps again, aiming closer
        assert await page.evaluate("[vid.currentTime, vid.muted, BG.on]") == [pytest.approx(40.4), True, True]
        await page.evaluate("at(vid, 40.33); tick(vid)")                     # in step: the video takes the sound back
        assert await page.evaluate("[vid.muted, vid.playbackRate, bgAudio.muted, bgAudio.paused, BG.on]") == [False, 1, True, False, False]
        speed = "r => { vid.playbackRate = r; vid.dispatchEvent(new Event('ratechange')); return [bgAudio.playbackRate, bgAudio.paused]; }"
        assert await page.evaluate(speed, 1.5) == [1.5, False]               # your speed: bgAudio takes it too
        assert await page.evaluate(speed, 1) == [1, False]

        await page.evaluate("vid.pause()")                                   # you pause it: the sound stops too
        assert await page.evaluate("[bgAudio.paused, bgAudio.muted, vid.muted, BG.on, BG.going, mediaPlaying()]") == [
            True, True, False, False, False, False]
        await page.evaluate("vid.play()")
        await page.click("#tabbar [data-tab=chat]")                          # leaving the Feed (or scrolling past) pauses it
        await page.wait_for_function("vid.paused")
        assert await page.evaluate("[bgAudio.paused, BG.going, mediaPlaying()]") == [True, False, False]

        assert errors == []
        await page.evaluate("Update.tryNow(true)")                          # nothing plays any more: the update goes in
        await page.wait_for_function("window.stay === undefined")           # reloaded (it cuts off fetches: no error check)
        await b.close()


@pytest.mark.e2e
async def test_lock_screen_shows_what_plays(bridge):
    """iOS shows one Now Playing for the whole app (lock screen, Dynamic Island). A Library file shows its own name and
    buttons, not the last feed post's, and takes them off when it closes. One sound at a time. A full-screen video you
    swipe away from pauses. A Library file that plays on with the screen off holds back app updates. Playback is faked."""
    lib = bridge["data"] / "lib" / "Sounds"
    lib.mkdir(parents=True, exist_ok=True)
    with wave.open(str(lib / "talk.wav"), "wb") as w:   # a real sound: a file that fails to load shows an error instead
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(16000 * 5))
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => {
          const M = HTMLMediaElement.prototype;
          Object.defineProperty(M, 'paused', {get() { return !this._on; }, configurable: true});
          Object.defineProperty(M, 'error', {get() { return null; }, configurable: true});
          M.play = function () { this._on = true; this.dispatchEvent(new Event('play')); return Promise.resolve(); };
          M.pause = function () { if (this._on) { this._on = false; this.dispatchEvent(new Event('pause')); } };
          window.msh = {};
          if (window.MediaSession) MediaSession.prototype.setActionHandler = (k, f) => { msh[k] = f; };
          window.title = () => navigator.mediaSession?.metadata?.title;
          window.setHidden = (h) => {
            Object.defineProperty(document, 'visibilityState', {get: () => h ? 'hidden' : 'visible', configurable: true});
            Object.defineProperty(document, 'hidden', {get: () => h, configurable: true});
            document.dispatchEvent(new Event('visibilitychange'));
          };
        }""")
        meta = await page.evaluate("!!navigator.mediaSession && !!window.MediaMetadata")
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        await page.evaluate("""() => { const t = F.data.tabs.foryou.posts;
          t.f1.media = [{type: 'video', w: 1280, h: 720, url: '', video: '/nope/a.mp4'}];
          t.f3.media = [{type: 'photo', w: 800, h: 600, url: ''}, {type: 'video', w: 1280, h: 720, url: '', video: '/nope/b.mp4'}];
          loadFeed = async () => {}; renderFeed();
          window.vid = document.querySelector('.feed-post[data-pid=f1] video'); vid.scrollIntoView({block: 'center'}); vid.play(); }""")
        assert await page.evaluate("NP.el === vid")
        if meta:
            assert await page.evaluate("title()") == "We shipped a new reasoning model today."

        await page.click("#tabbar [data-tab=library]")
        await page.click("#libSeg [data-v=all]")
        await page.click("#libraryList .item[data-dir='Sounds']")
        await page.click("#libraryList [data-path='Sounds/talk.wav'] .tx")
        await page.wait_for_selector("#fvBody audio")
        await page.evaluate("window.aud = $('#fvBody audio'); aud.play()")   # you press play
        assert await page.evaluate("[NP.el === aud, vid.paused]") == [True, True]
        if meta:
            assert await page.evaluate("title()") == "talk.wav"             # not the feed post
        if await page.evaluate("!!navigator.mediaSession"):                  # its buttons work the file, not the video
            await page.evaluate("msh.pause()")
            assert await page.evaluate("[aud.paused, vid.paused]") == [True, True]
            await page.evaluate("msh.play()")
            assert await page.evaluate("[aud.paused, vid.paused]") == [False, True]
        await page.evaluate("Update.pending = true; window.stay = 1; setHidden(true)")   # it plays on with the screen off
        await page.wait_for_timeout(700)
        assert await page.evaluate("[window.stay, mediaPlaying()]") == [1, True]   # no update cuts it off
        await page.evaluate("Update.pending = false; setHidden(false)")
        await page.click("#fvClose")
        assert await page.evaluate("[aud.paused, NP.el]") == [True, None]
        if meta:
            assert await page.evaluate("[title(), msh.play]") == [None, None]   # nothing left on the lock screen

        await page.click("#tabbar [data-tab=feed]")
        await page.evaluate("""window.vid = document.querySelector('.feed-post[data-pid=f1] video');   // (the feed was drawn again)
          vid.play(); openMedia('f3', 1)""")                                 # a full-screen video: one sound at a time
        assert await page.evaluate("[vid.paused, $('#mediaStage video').paused, NP.el === $('#mediaStage video')]") == [True, False, True]
        await page.evaluate("$('#mediaStage').scrollLeft = 0; $('#mediaStage').dispatchEvent(new Event('scroll'))")
        assert await page.evaluate("$('#mediaStage video').paused")         # swiped to the photo: it pauses
        await page.evaluate("closeMedia()")
        assert await page.evaluate("NP.el") is None
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_message_box_stays_one_line_and_nothing_scrolls_sideways(bridge):
    """A long chat name ends in "…" in the empty message box instead of a second line. A long command in a step, a long
    note or a long code line wraps or ends in "…": the chat never scrolls sideways."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        one = await page.evaluate("$('#input').offsetHeight")
        await page.evaluate("() => { curConv().title = 'Website thumbnail and reviewing activities from my emails'; setTitle(); }")
        ph = await page.get_attribute("#input", "placeholder")
        assert ph.startswith("Message in Website") and ph.endswith("…")
        assert await page.evaluate("$('#input').offsetHeight") == one
        await page.evaluate("""() => {
          const cmd = "grep -v 'option' /Users/alex/Documents/Milo/milo/data/claude/projects/-Users-alex-Documents-Milo/16e21692-075f-43f1-ad8f-e1f5ec2ac687/tool-results/mcp-milo-browser-browser_snapshot-1792340025590.txt | head -60";
          S.conv.messages.push({ role: 'assistant', text: '```\\n' + 'x'.repeat(300) + '\\n```', tools: [{ title: cmd, status: 'in_progress' }],
            notes: [{ kind: 'memory', text: 'y'.repeat(200) }] });
          curConv().running = true; renderMessages(true);
        }""")
        sizes = await page.evaluate("""() => [$('#chatScroll').scrollWidth - $('#chatScroll').clientWidth,
          document.documentElement.scrollWidth - innerWidth, $('.steps summary').getBoundingClientRect().right - innerWidth,
          $('.steps summary').offsetHeight]""")
        assert sizes[0] <= 0 and sizes[1] <= 0 and sizes[2] <= 0 and sizes[3] < 40   # the step stays a one-line pill
        assert await page.evaluate("getComputedStyle($('#chatScroll')).overflowX") == "hidden"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_send_shows_while_the_last_words_come_in(bridge):
    """After you stop recording, send shows at once (not the mic) while the last words are transcribed. Tapped then, it
    sends when they are in."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => {
          window.sendPrompt = (text, voice) => { window.sent = [text, voice]; return true; };
          window.transcribe = () => new Promise((r) => { window.release = () => r('buy oat milk'); });
          ptt.rec = { stop: async () => new Blob([new Uint8Array(2000)]), close() {}, chunks: [] };
          ptt.active = S.dictating = true; ptt.partial = null; renderComposer();
        }""")
        assert await page.is_visible("#micBtn") and await page.is_hidden("#sendBtn")   # recording: the mic (a stop)
        await page.evaluate("finishPtt(); 0")
        assert await page.is_visible("#sendBtn") and await page.is_hidden("#micBtn")
        await page.click("#sendBtn")
        assert await page.evaluate("window.sent") is None                          # waits for the last words
        await page.evaluate("release()")
        await page.wait_for_function("window.sent")
        assert await page.evaluate("window.sent") == ["buy oat milk", True]
        assert await page.is_visible("#micBtn") and await page.is_hidden("#sendBtn")
        assert errors == []
        await b.close()


TOUCH = """([sel, type, x, y]) => { const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'touches', { value: type === 'touchend' ? [] : [{ clientX: x, clientY: y }] });
  $(sel).dispatchEvent(e); return e.defaultPrevented; }"""


@pytest.mark.e2e
async def test_feed_quoted_post_shows_in_place_and_opens_on_its_own_page(bridge):
    """A quoted or linked X post shows inside the post that shares it: author, text, photos and video, with no counts or
    replies. A tap opens it on its own page in Milo, as on X (the user's ask, 2026-10-20): all its text, when, views and
    counts, Open in X and Ask Milo; Back or a swipe from the left edge goes back. It never opens X by itself: a photo
    opens full screen as that post, a video plays in place."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        await page.evaluate("""() => { F.data.tabs.foryou.posts.f1.quote = { id: 'q9', name: 'Quoted Author', handle: 'qauthor',
            avatar: '', text: 'Line\\n'.repeat(12) + 'the end', created: Date.now() / 1000 - 3600, views: 12345, likes: 1200,
            reposts: 1, quotes: 0, url: 'https://x.com/qauthor/status/q9', media: [
              { type: 'photo', w: 800, h: 600, alt: '', url: 'https://pbs.twimg.com/media/q1.jpg' },
              { type: 'photo', w: 800, h: 600, alt: '', url: 'https://pbs.twimg.com/media/q2.jpg' }] };
          renderFeed(); }""")
        q = ".feed-post[data-pid=f1] .feed-quote"
        await page.wait_for_selector(q)
        assert await page.eval_on_selector(q, "e => [e.tagName, e.querySelectorAll('a').length, e.querySelectorAll('.feed-stats').length]") \
            == ["DIV", 0, 0]                                                  # not a link, no counts
        assert "Quoted Author" in await page.inner_text(f"{q} .qh")
        assert await page.eval_on_selector_all(f"{q} [data-fmedia][data-fq]", "els => els.length") == 2
        popups = []
        page.context.on("page", lambda pg: popups.append(pg))
        assert await page.eval_on_selector(f"{q} p", "e => e.classList.contains('clamp')")
        await page.click(f"{q} p")                                            # its own page, as on X
        await page.wait_for_selector("#postView", state="visible")
        body = await page.inner_text("#pvBody")
        assert "Quoted Author" in body and "@qauthor" in body and "the end" in body
        stats = await page.eval_on_selector_all("#pvBody .feed-stats [data-stat]", "els => els.map(e => [e.dataset.stat, e.innerText])")
        assert stats == [["reposts", "1"], ["likes", "1.2k"], ["views", "12k"]]   # no zero or missing counts
        assert ":" in await page.inner_text("#pvBody .pv-time")
        assert await page.get_attribute("#pvBody a.feed-btn", "href") == "https://x.com/qauthor/status/q9"
        await page.click("#pvBody [data-fmedia][data-n='0']")                 # its photo, over its page
        await page.wait_for_selector("#mediaView", state="visible")
        await page.click("#mediaClose")
        await page.click("#pvBack")
        await page.wait_for_selector("#postView", state="hidden")
        await page.click(f"{q} .qh")
        await page.wait_for_selector("#postView", state="visible")
        for t, x in (("touchstart", 5), ("touchmove", 240), ("touchend", 240)):   # a swipe from the left edge
            await page.evaluate(TOUCH, ["#pvBody", t, x, 300])
        await page.wait_for_selector("#postView", state="hidden")
        await page.click(f"{q} [data-fmedia][data-n='1']")                    # the quoted post's photo, full screen
        await page.wait_for_selector("#mediaView", state="visible")
        assert "Quoted Author" in await page.inner_text("#mediaFoot") and await page.query_selector("#mediaFoot a") is None
        assert await page.eval_on_selector_all("#mediaStage img", "els => els.length") == 2
        await page.click("#mediaClose")
        await page.evaluate("""() => { F.data.tabs.foryou.posts.f1.quote = { id: 'q8', name: 'Video Person', handle: 'vid', text: 'clip',
            media: [{ type: 'video', w: 1280, h: 720, alt: '', url: 'https://pbs.twimg.com/ext_tw_video_thumb/1.jpg', video: '/none.mp4' }] };
          renderFeed(); }""")
        v = f"{q} video"                                                      # plays here, as a feed video
        assert await page.eval_on_selector(v, "e => [e.dataset.vpid, 'fq' in e.dataset, e.controls]") == ["f1", True, True]
        await page.click(f"{q} .qb")
        assert popups == [] and page.url.startswith(BASE) and await page.evaluate("S.tab") == "feed"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_quoted_post_page_shows_time_and_counts_like_a_post(bridge):
    """A quoted post's page shows when it was posted and the same counts row as a post in the feed (replies, reposts,
    likes, views, bookmarks with the same icons), the user's ask (2026-10-20). Counts it lacks are left out, and a
    quote with no time or counts (read before they were kept) shows neither, with no blanks or zeros."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        created = 1792000000
        await page.evaluate("""(c) => { F.data.tabs.foryou.posts.f1.quote = { id: 'q9', name: 'Quoted Author', handle: 'qauthor',
            avatar: '', text: 'hi', created: c, replies: 7, reposts: 3, likes: 1200, views: 12345, bookmarks: 40, quotes: 2,
            url: 'https://x.com/qauthor/status/q9', media: [] }; renderFeed(); }""", created)
        await page.click(".feed-post[data-pid=f1] .feed-quote .qh")
        await page.wait_for_selector("#postView", state="visible")
        stats = "#pvBody .feed-stats [data-stat]"
        rows = await page.eval_on_selector_all(stats, "els => els.map(e => [e.dataset.stat, e.innerText, e.querySelector('svg').outerHTML])")
        assert [r[:2] for r in rows] == [["replies", "7"], ["reposts", "3"], ["likes", "1.2k"], ["views", "12k"], ["bookmarks", "40"]]
        feed_icons = await page.eval_on_selector_all(".feed-post[data-pid=f1] > .fp .feed-stats svg", "els => els.map(e => e.outerHTML)")
        assert [r[2] for r in rows][:4] == feed_icons[:4]                  # the same icons as the post's own row
        want = await page.evaluate("""(c) => { const d = new Date(c * 1000);
            return `${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`; }""", created)
        assert await page.inner_text("#pvBody .pv-time") == want
        assert " · " in await page.inner_text("#pvBody .pv-who span")       # how long ago, as beside a post's handle
        await page.click("#pvBack")
        await page.wait_for_selector("#postView", state="hidden")
        await page.evaluate("""() => { F.data.tabs.foryou.posts.f1.quote = { id: 'q7', name: 'Old Quote', handle: 'old', avatar: '',
            text: 'kept before counts', media: [] }; renderFeed(); }""")
        await page.click(".feed-post[data-pid=f1] .feed-quote .qh")
        await page.wait_for_selector("#postView", state="visible")
        assert await page.query_selector("#pvBody .feed-stats") is None and await page.query_selector("#pvBody .pv-time") is None
        assert await page.inner_text("#pvBody .pv-who span") == "@old"
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_quoted_post_goes_back_to_the_post_that_quotes_it(bridge):
    """A quoted post's page goes back with a swipe right (from the edge or the middle), the Back button, Escape or the
    browser's back, and each lands on the post that quotes it at the same place on screen (the user's ask, 2026-10-20),
    also when the feed was redrawn with new posts meanwhile. A scroll up or down, or a swipe left, keeps the page open."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        await page.evaluate("""() => { const tab = F.data.tabs.foryou, mk = (id) => ({ ...tab.posts.f1, id, quote: null,
            text: id + ' ' + 'words '.repeat(40) });
          tab.top = [];
          for (let i = 0; i < 30; i++) { tab.posts['p' + i] = mk('p' + i); tab.top.push({ post: 'p' + i, why: '' }); }
          tab.posts.p15.quote = { id: 'q1', name: 'Quoted Author', handle: 'qa', avatar: '', text: 'quoted words '.repeat(80), media: [] };
          renderFeed(); }""")
        post = ".feed-post[data-pid=p15]"
        await page.evaluate(f"() => {{ const sc = $('#feedScroll'); sc.scrollTop += $('{post}').getBoundingClientRect().top - 300; }}")
        where = f"() => Math.round($('{post}').getBoundingClientRect().top)"
        at = await page.evaluate(where)
        assert 250 < at < 350 and await page.evaluate("$('#feedScroll').scrollTop") > 1000

        async def open_quote():
            await page.click(f"{post} .feed-quote .qh")
            await page.wait_for_selector("#postView:not(.out)", state="visible")
            assert await page.evaluate("history.state?.pv") == 1

        async def closed():
            await page.wait_for_selector("#postView", state="hidden")
            await page.wait_for_function("!history.state?.pv")              # its history entry is gone
            assert abs(await page.evaluate(where) - at) <= 2                 # back on the post, where it was
            assert await page.evaluate("$('#drawer').hidden && S.tab") == "feed"

        async def swipe(*pts):
            moved = []
            for t, (x, y) in zip(["touchstart"] + ["touchmove"] * (len(pts) - 2) + ["touchend"], pts):
                moved.append(await page.evaluate(TOUCH, ["#pvBody", t, x, y]))
            return moved

        await open_quote()
        await page.evaluate("""() => { const tab = F.data.tabs.foryou;   // new posts come in above while it is open
          for (let i = 0; i < 5; i++) { tab.posts['n' + i] = { ...tab.posts.p0, id: 'n' + i }; tab.top.unshift({ post: 'n' + i, why: '' }); }
          renderFeed(); }""")
        assert await page.query_selector(".feed-post[data-pid=n0]") is None   # not redrawn under the open page
        await swipe((150, 400), (160, 300), (170, 150), (170, 150))            # a scroll: stays open
        await swipe((300, 400), (200, 402), (100, 404), (100, 404))            # a swipe left: stays open
        await page.wait_for_timeout(300)
        assert await page.is_visible("#postView")
        moved = await swipe((150, 400), (175, 402), (260, 405), (360, 405), (360, 405))   # a swipe right from the middle
        assert moved[2] is True                                                # it slides; the page doesn't scroll
        await closed()
        assert await page.query_selector(".feed-post[data-pid=n0]")            # the new posts came in on the way back

        await open_quote()
        await page.click("#pvBack")
        await closed()
        await open_quote()
        await swipe((5, 300), (60, 300), (240, 300), (240, 300))               # from the left edge
        await closed()
        await open_quote()
        await page.go_back()                                                   # the browser's back
        await closed()
        await open_quote()
        await page.keyboard.press("Escape")
        await closed()
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_feed_photo_zooms_and_pulls_down_to_close(bridge):
    """A feed photo zooms with a pinch or a double tap. Pulled down far enough, it closes; a short pull springs back.
    A sheet pulled down by its header closes too."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.click("#tabbar [data-tab=feed]")
        await page.click("#feedSeg [data-ftab=foryou]")
        await page.wait_for_selector(".feed-post[data-pid=f1]")
        await page.evaluate("""() => { F.data.tabs.foryou.posts.f1.media = [{ type: 'photo', w: 800, h: 600, url: 'https://pbs.twimg.com/media/a.jpg' }];
          renderFeed(); openMedia('f1', 0); }""")
        await page.wait_for_selector("#mediaView", state="visible")
        pinch = """([type, scale]) => { const e = new Event(type, { bubbles: true, cancelable: true });
          Object.assign(e, { scale, clientX: 200, clientY: 300 }); $('#mediaStage img').dispatchEvent(e); return e.defaultPrevented; }"""
        for t, scale in [("gesturestart", 1), ("gesturechange", 2), ("gestureend", 2)]:
            assert await page.evaluate(pinch, [t, scale])
        assert await page.evaluate("[MZ.zoom, $('#mediaView').classList.contains('zoomed')]") == [2, True]
        await page.click("#mediaStage .media-zoom", click_count=1)
        await page.click("#mediaStage .media-zoom", click_count=1)                # a double tap: back out
        assert await page.evaluate("MZ.zoom") == 1

        assert await page.evaluate(TOUCH, ["#mediaStage img", "touchstart", 200, 300]) is False
        await page.wait_for_timeout(100)                                        # a slow pull (a quick flick closes)
        assert await page.evaluate(TOUCH, ["#mediaStage img", "touchmove", 201, 315])   # down: the picture follows
        await page.wait_for_timeout(100)
        await page.evaluate(TOUCH, ["#mediaStage img", "touchmove", 201, 330])
        await page.wait_for_timeout(100)
        await page.evaluate(TOUCH, ["#mediaStage img", "touchend", 0, 0])         # 30 px: it springs back
        await page.wait_for_timeout(300)
        assert await page.is_visible("#mediaView") and await page.evaluate("$('#mediaStage').style.transform") == ""
        await page.evaluate(TOUCH, ["#mediaStage img", "touchstart", 200, 300])
        await page.evaluate(TOUCH, ["#mediaStage img", "touchmove", 201, 320])
        await page.evaluate(TOUCH, ["#mediaStage img", "touchmove", 202, 520])
        await page.evaluate(TOUCH, ["#mediaStage img", "touchend", 0, 0])
        await page.wait_for_selector("#mediaView", state="hidden")

        await page.click(".feed-brief li:first-child .feed-src")
        await page.wait_for_function("$('#feedSources').classList.contains('open')")
        await page.wait_for_timeout(350)
        await page.evaluate(TOUCH, ["#feedSources .sheet-head", "touchstart", 200, 500])
        await page.evaluate(TOUCH, ["#feedSources .sheet-head", "touchmove", 200, 510])
        await page.evaluate(TOUCH, ["#feedSources .sheet-head", "touchmove", 200, 700])
        await page.evaluate(TOUCH, ["#feedSources .sheet-head", "touchend", 0, 0])
        await page.wait_for_function("!$('#feedSources').classList.contains('open')")
        await page.wait_for_selector("#feedSources", state="hidden")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_other_apps_keep_their_sound_and_the_chat_shows_no_size(bridge):
    """Taps and messages play nothing (any play() stops music in other apps) unless replies are read aloud. The chat's
    size in tokens shows nowhere: the user talks to Milo, not to a session."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("window.send = (o) => { window.lastSend = o; return true; }; 0")
        await page.click("#tabbar [data-tab=goals]")
        await page.click("#tabbar [data-tab=chat]")
        await page.evaluate("sendPrompt('hi', false)")
        assert await page.evaluate("[audioUnlocked, BG.unlocked, player.paused, bgAudio.paused]") == [False, False, True, True]
        await page.evaluate("S.speakPolicy = 'always'; sendPrompt('hi again', false)")
        assert await page.evaluate("audioUnlocked")                                # replies will be read aloud

        await page.evaluate("() => { S.speakPolicy = 'never'; curConv().used = 70500; renderMessages(); }")
        assert await page.locator(".msg-tokens").count() == 0 and "tokens" not in await page.inner_text("#messages")
        assert errors == []
        await b.close()


@pytest.mark.e2e
async def test_music_in_other_apps_goes_on_when_milo_opens(bridge):
    """iOS starts a kept AudioContext again each time the app comes back, which stopped the user's music on every
    open. Milo keeps none: reading aloud makes no context, and voice mode closes its meter's context on exit."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, permissions=["microphone"])
        await page.evaluate("""() => {
            const A = window.AudioContext || window.webkitAudioContext;
            window.ctxs = [];
            window.AudioContext = window.webkitAudioContext = class extends A { constructor(...a) { super(...a); ctxs.push(this); } };
            window.send = (o) => true;
        }""")
        # replies read aloud: the silent clip unlocks the player, but no AudioContext is left for iOS to start again
        await page.evaluate("S.speakPolicy = 'always'; sendPrompt('hi', false)")
        assert await page.evaluate("audioUnlocked")
        assert await page.evaluate("[ctxs.length, audioCtx]") == [0, None]
        # a tap on an approval with replies read only for voice plays nothing
        await page.evaluate("audioUnlocked = false; player.src = ''; S.speakPolicy = 'voice'; answerApproval('a1', 'allow_once')")
        assert await page.evaluate("[audioUnlocked, ctxs.length]") == [False, 0]
        # voice mode: the meter's context lives only while you talk to Milo
        await page.evaluate("S.voiceInput = true; Voice.enter()")
        await page.wait_for_function("Voice.on && ctxs.length === 1")
        await page.evaluate("Voice.exit()")
        await page.wait_for_function("ctxs[0].state === 'closed'")
        assert await page.evaluate("audioCtx") is None
        assert errors == []
        await b.close()


# real agent runs


async def run_prompt(text, on_event=None, timeout=300):
    """Send a prompt over /ws and collect events until the task is done. on_event may answer approvals."""
    events = []
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws?token={TOKEN}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "prompt", "id": None, "text": text, "ref": "r"}))
        conv = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            ev = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.time()))
            events.append(ev)
            if ev["t"] == "bound":
                conv = ev["id"]
            if on_event:
                await on_event(ev, ws)
            if ev["t"] == "done" and ev["id"] == conv:
                return conv, ev["message"], events
    raise AssertionError("task did not finish in time")


@pytest.mark.agent
async def test_agent_purchase_waits_for_approval(bridge, remote, site_url):
    titles = []

    async def deny(ev, ws):
        if ev["t"] == "approval":
            titles.append(ev["approval"]["title"])
            await ws.send(json.dumps({"type": "approve", "approval": ev["approval"]["id"], "option": "reject_once"}))

    await run_prompt(f"Open {site_url}/shop.html and click the Buy now button once.", deny)
    assert any("Buy now" in t for t in titles), titles
    assert await (await page_with(remote, "shop.html")).text_content("#bought") == "0"

    async def allow(ev, ws):
        if ev["t"] == "approval":
            await ws.send(json.dumps({"type": "approve", "approval": ev["approval"]["id"], "option": "allow_once"}))

    await run_prompt(f"Open {site_url}/shop.html and click the Buy now button once. I approve it.", allow)
    assert await (await page_with(remote, "shop.html")).text_content("#bought") == "1"


@pytest.mark.agent
async def test_agent_logs_in_without_seeing_the_password(bridge, remote, site_url):
    await api("POST", "/api/accounts", json={"domain": "127.0.0.1", "username": "tester", "password": TEST_PASSWORD,
                                             "label": "Test site", "policy": "ask"})
    asked = []

    async def allow(ev, ws):
        if ev["t"] == "approval":
            asked.append(ev["approval"]["title"])
            await ws.send(json.dumps({"type": "approve", "approval": ev["approval"]["id"], "option": "allow_once"}))

    _, msg, events = await run_prompt(
        f"Log in to {site_url}/login.html with my saved account, then tell me what the status line says.", allow)
    assert "Log in to 127.0.0.1 as tester?" in asked
    assert await (await page_with(remote, "login.html")).text_content("#status") == "Welcome, tester"
    assert "Welcome" in msg["text"]

    # the password must not appear anywhere the model, logs or app data could see it
    assert TEST_PASSWORD not in json.dumps(events)
    leaks = []
    for f in bridge["data"].rglob("*"):
        if f.is_file() and "browser-profile" not in f.parts and TEST_PASSWORD.encode() in f.read_bytes():
            leaks.append(str(f))
    goose_db = Path.home() / ".local/share/goose/sessions/sessions.db"
    if goose_db.exists() and TEST_PASSWORD.encode() in goose_db.read_bytes():
        leaks.append(str(goose_db))
    # Claude Code's own transcripts for this bridge (its working folder is the test data folder)
    slug = re.sub(r"[^A-Za-z0-9-]", "-", str(bridge["data"].resolve()))
    transcripts = [f for base in (Path.home() / ".claude/projects", Path.home() / ".claude-personal/projects")
                   for f in (base / slug).glob("*.jsonl")]
    assert transcripts, "found no Claude Code transcripts to check"
    assert any(b"browser_fill_credential" in f.read_bytes() for f in transcripts)   # the safe path was used
    leaks += [str(f) for f in transcripts if TEST_PASSWORD.encode() in f.read_bytes()]
    assert leaks == []


@pytest.mark.agent
async def test_agent_hands_over_for_a_captcha(bridge, remote, site_url):
    saw = []

    async def give_back(ev, ws):
        if ev["t"] == "browser" and ev["state"].get("controller") == "user" and ev["state"].get("reason") and not saw:
            saw.append(ev["state"]["reason"])
            human = await page_with(remote, "check.html")
            await human.click("#human")                      # the "user" solves it
            await api("POST", "/api/browser/control", json={"action": "release"})

    _, msg, _ = await run_prompt(f"Open {site_url}/check.html and get past the human check.", give_back)
    assert saw, "Milo never asked for a takeover"
    assert await (await page_with(remote, "check.html")).text_content("#result") == "Verified"


@pytest.mark.e2e
async def test_stop_with_agents_offers_undo(bridge):
    """A Stop that would end helper agents waits a few seconds: a pop-up says so and has Undo. Undo tells the Mac to
    keep going; the pop-up gives way to the result."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate("""() => { window.sent = []; const s = S.ws.send.bind(S.ws);
          S.ws.send = (m) => { window.sent.push(JSON.parse(m)); s(m); }; }""")
        await page.evaluate("handle({ t: 'stopping', id: 'u1', agents: 2, grace: 5 })")
        assert await page.is_visible("#undoStop")
        assert await page.text_content("#undoStop span") == "Stopping Milo and 2 helper agents"
        await page.click("#undoStop button")
        assert {"type": "keep", "id": "u1"} in await page.evaluate("window.sent")
        await page.evaluate("handle({ t: 'stop_undone', id: 'u1' })")
        await page.wait_for_function("$('#undoStop').hidden")
        assert await page.text_content("#toast") == "Milo keeps going"
        await page.evaluate("handle({ t: 'stopping', id: 'u2', agents: 1, grace: 5 })")
        assert await page.text_content("#undoStop span") == "Stopping Milo and 1 helper agent"
        await page.evaluate("handle({ t: 'toast', stop: true, text: 'Stopped Milo and 1 helper agent' })")
        await page.wait_for_function("$('#undoStop').hidden")
        assert await page.text_content("#toast") == "Stopped Milo and 1 helper agent"
        await page.evaluate("handle({ t: 'stopping', id: 'u3', agents: 1, grace: 0.2 })")
        await page.wait_for_function("$('#undoStop').hidden")   # the wait ran out
        assert errors == []
        await b.close()
