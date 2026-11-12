"""Mermaid diagrams in Milo's replies (web/app.js mmdFig, mmdDraw, mmdImg; web/vendor/mermaid).

Unit: md() runs in node, cut from app.js (test_rich_tables' runner). e2e: the real app in WebKit at iPhone 15 Pro size.
"""

import base64
import re
from urllib.parse import unquote

import pytest
from playwright.async_api import async_playwright

from conftest import ROOT
from test_rich_tables import md

VENDOR = ROOT / "web" / "vendor" / "mermaid"

FLOW = "flowchart LR\n  A[Phone] -->|Tailscale| B(Bridge)\n  B --> C{Goose}\n  C --> D[Claude]"
SEQ = "sequenceDiagram\n  participant U as User\n  U->>Milo: Plan my week\n  Milo-->>U: Here it is"
GANTT = "gantt\n  title Week\n  dateFormat YYYY-MM-DD\n  section Work\n  Draft :a1, 2026-10-20, 3d\n  Review :after a1, 2d"
CLASS = "classDiagram\n  class Hub {\n    +send(text)\n    +cancel()\n  }\n  Hub <|-- Bridge"
STATE = "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running : send\n  Running --> Idle : done\n  Running --> [*]"
DIAGRAMS = [FLOW, SEQ, GANTT, CLASS, STATE]
BAD = "flowchart LR\n  A --> \n  B -->> ]]"


def fence(src, lang="mermaid"):
    return f"Here:\n\n```{lang}\n{src}\n```\n\nDone."


def test_vendored_locally():
    """Mermaid is in web/vendor (the phone may have no internet), as the ESM build with its lazy chunks."""
    main = (VENDOR / "mermaid.esm.min.mjs").read_text()
    chunks = re.findall(r'"\./(chunks/mermaid\.esm\.min/[\w.-]+\.mjs)"', main)
    assert chunks and all((VENDOR / c).is_file() for c in chunks)
    assert (VENDOR / "LICENSE").is_file() and "Mermaid" in (VENDOR / "VERSION").read_text()
    assert "/vendor/mermaid/mermaid.esm.min.mjs" in (ROOT / "web" / "app.js").read_text()   # loaded from the Mac, not a CDN


def test_finished_block_waits_for_the_drawing_not_as_code():
    [h] = md([fence(FLOW), False])
    assert '<span class="fig svg mermaid loading" data-mmd="' in h
    assert "<pre>" not in h and "Tailscale" not in h and h.endswith("<p>Done.</p>")


def test_streaming_block_is_not_drawn():
    """A block still coming in has no closing fence: a placeholder, not queued for drawing, no source flashing by."""
    text = fence(FLOW)
    start = text.index("```mermaid")
    for n in range(start + len("```mermaid\n"), text.index("```", start + 3)):
        [h] = md([text[:n], True])
        assert '<span class="fig svg mermaid loading"><img alt=""></span>' in h, (n, h)
        assert "data-mmd" not in h and "<pre>" not in h and "Diagram error" not in h, (n, h)


def test_other_code_blocks_and_case():
    py, upper = md([fence("print(1)", "python"), False], [fence(SEQ, "Mermaid"), False])
    assert "<pre><code>print(1)</code></pre>" in py and "mermaid" not in py
    assert "fig svg mermaid" in upper


def test_empty_block_is_an_error_not_a_spinner():
    [h] = md(["```mermaid\n\n```", False])
    assert "mermaid-bad" in h and "Diagram error" in h and "loading" not in h


# e2e: the app in WebKit at iPhone size


from test_bridge_e2e import BASE, FAKE_CHAT, bridge, phone_page  # noqa: E402,F401  (the test bridge, own port and data)

SHOW = """(t) => { S.conv.messages.push({ role: 'user', text: 'Draw it' },
    { role: 'assistant', text: t, tools: [], notes: [] }); renderMessages(true); }"""
DRAWN = """(k) => { const f = [...document.querySelectorAll('.msg.assistant:last-child .bubble > .fig.mermaid, .msg.assistant:last-child .bubble > .mermaid-bad')];
    return f.length >= k && f.every((x) => x.classList.contains('mermaid-bad') || (!x.classList.contains('loading') && x.querySelector('img').naturalWidth > 0)); }"""


def svg_of(src):
    return base64.b64decode(src.split(",", 1)[1]).decode()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_five_kinds_draw_offline_fit_and_enlarge(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        outside = []
        page.on("request", lambda r: None if r.url.startswith(BASE) or r.url.startswith("data:") else outside.append(r.url))
        await page.evaluate(FAKE_CHAT)
        await page.evaluate(SHOW, "Kinds:\n\n" + "\n\n".join(f"```mermaid\n{d}\n```" for d in DIAGRAMS))
        await page.wait_for_function(DRAWN, arg=5, timeout=30000)
        m = await page.evaluate("""() => [...document.querySelectorAll('.msg.assistant:last-child .fig.mermaid')].map((f) => {
            const i = f.querySelector('img'), r = i.getBoundingClientRect(), bub = f.closest('.bubble').getBoundingClientRect();
            return { src: i.getAttribute('src'), w: i.naturalWidth, h: i.naturalHeight, inside: r.left >= bub.left - 0.5 && r.right <= bub.right + 0.5,
              bad: !!f.closest('.bubble').querySelector('.mermaid-bad') }; })""")
        assert len(m) == 5 and not any(x["bad"] for x in m), m
        for x in m:
            assert x["src"].startswith("data:image/svg+xml;base64,") and x["w"] > 20 and x["h"] > 20 and x["inside"], x
        texts = [svg_of(x["src"]) for x in m]
        for word, svg in zip(["Tailscale", "Plan my week", "Draft", "Hub", "Running"], texts):
            assert word in svg and "#ffffff" in svg, word   # light theme by default
        assert not await page.evaluate("document.querySelector('body > [id^=dmmd-], body > svg[id^=mmd-]') !== null")
        assert not outside, outside
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.locator(".msg.assistant:last-child .fig.mermaid img").first.click()
        await page.wait_for_selector("#mediaView:not([hidden]) #mediaStage img")
        assert (await page.get_attribute("#mediaStage img", "src")) == m[0]["src"]
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_bad_syntax_shows_source_and_a_note(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate(SHOW, fence(BAD))
        await page.wait_for_selector(".msg.assistant:last-child .mermaid-bad", timeout=30000)
        bad = page.locator(".msg.assistant:last-child .mermaid-bad")
        assert "B -->> ]]" in await bad.locator("pre").inner_text()
        assert (await bad.locator(".mermaid-err").inner_text()) == "Diagram error"
        assert await bad.locator(".mermaid-err").get_attribute("title")   # the parser's reason, on a long press
        assert not await page.evaluate("document.querySelector('body > [id^=dmmd-], body > svg[id^=mmd-]') !== null")
        # a good one after it still draws
        await page.evaluate(SHOW, fence(FLOW))
        await page.wait_for_function(DRAWN, arg=1, timeout=30000)
        assert await page.locator(".msg.assistant:last-child .fig.mermaid:not(.loading) img").count() == 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_streaming_block_draws_only_when_closed(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push({ role: 'user', text: 'Draw it' },
            { role: 'assistant', text: '', tools: [], notes: [] }); curConv().running = true; renderMessages(true); }""")
        text = fence(FLOW)
        close = text.index("```", text.index("```mermaid") + 3)
        seen = await page.evaluate("""([text, close]) => {
            const m = S.conv.messages.at(-1), seen = [];
            for (let n = 1; n < close; n += 2) {
              m.text = text.slice(0, n); renderMessages();
              const bub = document.querySelector('.msg.assistant:last-child .bubble');
              seen.push({ n, queued: MMD.ids.size, bad: !!bub?.querySelector('.mermaid-bad'), src: /Tailscale/.test(bub?.innerText || '') });
            }
            return seen;
          }""", [text, close])
        assert all(s["queued"] == 0 and not s["bad"] and not s["src"] for s in seen), [s for s in seen if s["queued"] or s["bad"] or s["src"]][:3]
        await page.evaluate("""(t) => { const m = S.conv.messages.at(-1); m.text = t; curConv().running = false; renderMessages(); }""", text)
        await page.wait_for_function(DRAWN, arg=1, timeout=30000)
        assert await page.evaluate("MMD.ids.size") == 1
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_dark_theme(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, color_scheme="dark")
        await page.evaluate(FAKE_CHAT)
        await page.evaluate(SHOW, fence(SEQ))
        await page.wait_for_function(DRAWN, arg=1, timeout=30000)
        svg = svg_of(await page.get_attribute(".msg.assistant:last-child .fig.mermaid img", "src"))
        assert "#30302e" in svg and "#ffffff" not in unquote(svg).split(">", 1)[0]
        # switching the phone to light redraws it in the light theme
        await page.emulate_media(color_scheme="light")
        await page.wait_for_function("""() => { const i = document.querySelector('.msg.assistant:last-child .fig.mermaid:not(.loading) img');
            return i && atob(i.getAttribute('src').split(',')[1]).includes('background-color:#ffffff'); }""", timeout=30000)
        assert errors == []
        await b.close()
