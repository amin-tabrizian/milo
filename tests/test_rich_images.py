"""Pictures in Milo's replies (web/app.js imgSrc, figHtml, cleanSvg, svgFig, openFigure; style.css .fig).

Unit: md() and cleanSvg() in the real app in WebKit (cleanSvg needs the browser's SVG parser).
e2e: a reply with a Library picture, a broken one and an svg block, at iPhone 15 Pro size: sized to the bubble,
tap to open, pinch, close.
"""

import struct
from urllib.parse import quote
import zlib

import httpx
import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from test_bridge_e2e import FAKE_CHAT, TOKEN, bridge, phone_page  # noqa: F401  (bridge: the test server fixture)

pytestmark = pytest.mark.asyncio(loop_scope="module")


def png(w, h, rgb=(40, 120, 200)):
    """A plain PNG of one colour."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        yield page, errors
        await b.close()


def frag(page, src, live=False):
    """md() into a detached element, so tests can query what it made."""
    return page.evaluate("([s, live]) => { const d = document.createElement('div'); d.innerHTML = md(s, live); window._d = d; return d.innerHTML; }",
                         [src, live])


# unit


@pytest.mark.e2e
async def test_markdown_image_with_caption(app):
    page, _ = app
    await frag(page, 'Here:\n\n![A cat](https://example.com/cat.jpg "My cat Tom")\n\nDone.')
    got = await page.evaluate("""() => { const f = _d.querySelector('.fig'), i = f.querySelector('img');
      return [i.getAttribute('src'), i.alt, i.getAttribute('loading'), i.dataset.cap, f.querySelector('.figcap').textContent,
              f.classList.contains('loading'), _d.querySelectorAll('a').length]; }""")
    assert got == ["https://example.com/cat.jpg", "A cat", "lazy", "My cat Tom", "My cat Tom", True, 0]
    # no title: the alt is the caption; no alt either: no caption
    await frag(page, "![Sales by month](https://example.com/s.png) and ![](https://example.com/t.png)")
    assert await page.evaluate("[..._d.querySelectorAll('.fig')].map((f) => f.querySelector('.figcap')?.textContent ?? null)") == \
        ["Sales by month", None]
    # inside code it stays text
    await frag(page, "`![x](https://example.com/a.png)`")
    assert await page.evaluate("_d.querySelectorAll('.fig').length") == 0


@pytest.mark.e2e
async def test_library_paths_become_file_links(app):
    page, _ = app
    await frag(page, "![Plot](charts/q3.png)")
    assert await page.evaluate("_d.querySelector('.fig img').getAttribute('src')") == \
        f"/api/picture?path=charts%2Fq3.png&token={TOKEN}"
    await frag(page, "![](<~/Documents/Milo/Library/Reports/a b.png>)")   # a space needs the <> form
    assert "path=Reports%2Fa%20b.png" in await page.evaluate("_d.querySelector('.fig img').getAttribute('src')")
    # a line that is only a saved picture's path shows the picture
    await frag(page, "Saved it:\n\n`/Users/me/Documents/Milo/Library/plot.svg`\n\nOpen it any time.")
    assert await page.evaluate("[_d.querySelectorAll('.fig').length, _d.querySelector('.fig .fig-bad span').textContent]") == \
        [1, "plot.svg"]
    # a path inside a sentence stays text
    await frag(page, "I saved /Users/me/plot.png for you.")
    assert await page.evaluate("_d.querySelectorAll('.fig').length") == 0


@pytest.mark.e2e
async def test_full_paths_with_spaces_become_pictures(app):
    """#76: Milo wrote ![t](/Users/.../Library/Calories and weight.png): a space breaks Markdown's image, so it showed
    as text. A full path that ends in a picture's name counts, with spaces, ( ) in the name, a caption, or in <>."""
    page, _ = app
    for src, path in [("/Users/me/Documents/Milo/Library/Calories and weight.png", "/Users/me/Documents/Milo/Library/Calories and weight.png"),
                      ('/Users/me/Documents/Milo/Temp/Sleep (week).PNG "Last week"', "/Users/me/Documents/Milo/Temp/Sleep (week).PNG"),
                      ("<~/Documents/Milo/Temp/a b.svg>", "~/Documents/Milo/Temp/a b.svg"),
                      ("~/Documents/Milo/Library/Health/w t.jpg", "Health/w t.jpg")]:
        await frag(page, f"Here it is:\n\n![Calories and weight]({src})\n\nMore text.")
        got = await page.evaluate("[_d.querySelectorAll('.fig').length, _d.querySelector('.fig img')?.getAttribute('src'), "
                                  "_d.textContent.includes('![')]")
        assert got == [1, f"/api/picture?path={quote(path, safe='()~')}&token={TOKEN}", False], src
    # still text: not a picture, not a full path, or a home path outside Milo
    for src in ["/Users/me/notes and plans.txt", "charts/a b.png", "~/.ssh/a b.png"]:
        assert "<img" not in await frag(page, f"![x]({src})"), src


@pytest.mark.e2e
async def test_unsafe_image_sources_stay_text(app):
    page, _ = app
    for src in ["javascript:alert(1)", "vbscript:x.png", "data:text/html;base64,PHNjcmlwdD4=", "~/.ssh/id_rsa.png",
                "notes.txt", 'x.png" onerror="window.pwned=1']:
        html = await frag(page, f"![bad]({src})")
        assert "<img" not in html, src
    # a quote in the caption cannot leave the attribute
    await frag(page, '![a](https://example.com/a.png "x\\" onload=\\"window.pwned=1")')
    assert await page.evaluate("[...document.querySelectorAll('[onload]')].length + (_d.querySelector('[onload]') ? 1 : 0)") == 0
    assert await page.evaluate("window.pwned") is None


EVIL_SVG = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 200 100" onload="window.pwned=1">
  <title>Evil plot</title>
  <script>window.pwned = 2</script>
  <style>@import url(https://evil.example/x.css); rect { fill: red }</style>
  <style>.ok { fill: blue }</style>
  <rect class="ok" width="50" height="50" onclick="window.pwned=3" style="fill: url(https://evil.example/t.png)"/>
  <a href="javascript:window.pwned=4"><circle cx="10" cy="10" r="5"/></a>
  <foreignObject width="100" height="100"><div xmlns="http://www.w3.org/1999/xhtml"><img src="x" onerror="window.pwned=5"/></div></foreignObject>
  <animate attributeName="href" to="javascript:window.pwned=6"/>
  <set attributeName="onmouseover" to="window.pwned=7"/>
  <image href="https://evil.example/track.png" width="10" height="10"/>
  <image xlink:href="data:image/png;base64,iVBORw0KGgo=" width="10" height="10"/>
  <use href="https://evil.example/s.svg#a"/>
  <use href="#dot"/>
  <iframe xmlns="http://www.w3.org/1999/xhtml" src="javascript:window.pwned=8"/>
</svg>"""


@pytest.mark.e2e
async def test_svg_is_cleaned_of_anything_that_runs_or_reaches_out(app):
    """Security: scripts, handlers, foreign HTML, links, animation and outside URLs are all removed; nothing runs."""
    page, errors = app
    out = await page.evaluate("(s) => cleanSvg(s)", EVIL_SVG)
    low = out.lower()
    for bad in ["<script", "onload", "onclick", "foreignobject", "<a ", "<animate", "<set", "<iframe", "javascript:",
                "evil.example", "@import", "pwned"]:
        assert bad not in low, bad
    for kept in ["<title>Evil plot</title>", ".ok { fill: blue }", 'class="ok"', 'href="#dot"', "data:image/png;base64",
                 'width="200"', 'fill="#fff"']:
        assert kept in out, kept
    # shown in a reply it is an <img> of a data URL, and the page never ran any of it
    await page.evaluate(FAKE_CHAT)
    await page.evaluate("(s) => { S.conv.messages[1].text = 'Here:\\n\\n```svg\\n' + s + '\\n```'; renderAll(); }", EVIL_SVG)
    await page.wait_for_selector("#messages .fig.svg img")
    assert await page.evaluate("[document.querySelectorAll('#messages svg script, #messages foreignObject').length, "
                               "$('#messages .fig.svg img').src.startsWith('data:image/svg+xml;base64,'), "
                               "$('#messages .fig.svg .figcap').textContent]") == [0, True, "Evil plot"]
    await page.wait_for_timeout(300)
    assert await page.evaluate("window.pwned") is None
    assert errors == []


@pytest.mark.e2e
async def test_svg_block_while_streaming_and_when_broken(app):
    page, _ = app
    half = '```svg\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect wid'
    await frag(page, half, True)
    assert await page.evaluate("[_d.querySelectorAll('.fig.svg.loading').length, _d.textContent.includes('rect')]") == [1, False]
    # not an svg, or not well formed: shown as code
    for bad in ["<svg><rect></svg>", "<html><body>hi</body></html>", '<svg xmlns="http://www.w3.org/2000/svg"><rect']:
        await frag(page, f"```svg\n{bad}\n```")
        assert await page.evaluate("[_d.querySelectorAll('.fig').length, _d.querySelectorAll('pre code').length]") == [0, 1], bad


# e2e


@pytest.mark.e2e
async def test_reply_pictures_fit_open_zoom_and_close(bridge, app):
    """A Library plot shows sized to the bubble; a missing one shows a quiet line. A tap opens it full screen with its
    caption; a pinch zooms; the close button brings back the chat."""
    page, errors = app
    lib = bridge["data"] / "lib"
    lib.mkdir(exist_ok=True)
    (lib / "wide-plot.png").write_bytes(png(1600, 600))
    text = ("Here is the plot:\n\n![Revenue by quarter](wide-plot.png \"Revenue, 2026\")\n\n"
            "And the old one:\n\n![](gone.png)\n\n"
            '```svg\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"><title>Bars</title>'
            '<rect x="10" y="20" width="20" height="40" fill="#36c"/></svg>\n```')
    await page.evaluate(FAKE_CHAT)
    await page.evaluate("(t) => { S.conv.messages[1].text = t; renderAll(); }", text)
    await page.wait_for_function("$$('#messages .fig').length === 3 && !$('#messages .fig.loading')")
    got = await page.evaluate("""() => { const [plot, gone, svg] = $$('#messages .fig'), bubble = plot.closest('.md');
      const r = plot.querySelector('img').getBoundingClientRect(), b = bubble.getBoundingClientRect();
      return { w: r.width, bw: b.width, right: r.right <= b.right + 0.5, vw: innerWidth, sx: document.scrollingElement.scrollWidth,
               broken: gone.classList.contains('broken'), badShown: getComputedStyle(gone.querySelector('.fig-bad')).display,
               goneImg: getComputedStyle(gone.querySelector('img')).display, badName: gone.querySelector('.fig-bad span').textContent,
               svgOk: !svg.classList.contains('broken') && svg.querySelector('img').naturalWidth > 0,
               plotBad: getComputedStyle(plot.querySelector('.fig-bad')).display }; }""")
    assert 0 < got["w"] <= got["bw"] and got["right"] and got["sx"] <= got["vw"]   # never wider than the bubble or the phone
    assert got["broken"] and got["badShown"] == "flex" and got["goneImg"] == "none" and got["badName"] == "gone.png"
    assert got["svgOk"] and got["plotBad"] == "none"

    # rebuilt (as while a reply streams), a loaded picture shows at once, without the placeholder
    await page.evaluate("S.conv.messages[1].text += ' '; S.conv.messages[1]._html = null; renderAll()")
    assert await page.evaluate("[!!$('#messages .fig.loading'), !!$$('#messages .fig')[1].classList.contains('broken')]") == [False, True]

    # a broken picture does not open; a good one does, with its caption
    await page.click("#messages .fig.broken .fig-bad")
    assert await page.is_hidden("#mediaView")
    await page.click("#messages .fig img >> nth=0")
    await page.wait_for_selector("#mediaView", state="visible")
    assert await page.evaluate("[$('#mediaStage .media-zoom img').getAttribute('src').includes('wide-plot.png'), "
                               "$('#mediaFoot .figcap').textContent, $('#mediaCount').textContent]") == [True, "Revenue, 2026", ""]
    pinch = """([type, scale]) => { const e = new Event(type, { bubbles: true, cancelable: true });
      Object.assign(e, { scale, clientX: 200, clientY: 300 }); $('#mediaStage img').dispatchEvent(e); return e.defaultPrevented; }"""
    for t, scale in [("gesturestart", 1), ("gesturechange", 2), ("gestureend", 2)]:
        assert await page.evaluate(pinch, [t, scale])
    assert await page.evaluate("[MZ.zoom, $('#mediaView').classList.contains('zoomed')]") == [2, True]
    await page.click("#mediaClose")
    await page.wait_for_selector("#mediaView", state="hidden")

    # the svg opens too, on its white paper
    await page.click("#messages .fig.svg img")
    await page.wait_for_selector("#mediaView", state="visible")
    assert await page.evaluate("[$('#mediaStage .media-zoom').classList.contains('svg'), $('#mediaFoot .figcap').textContent, MZ.zoom]") == \
        [True, "Bars", 1]
    await page.click("#mediaClose")
    await page.wait_for_selector("#mediaView", state="hidden")
    assert errors == []


@pytest.mark.e2e
async def test_a_temp_plot_by_full_path_shows_and_opens(bridge, app):
    """#76: a plot Milo saved in Temp (not the Library), named by its full path with spaces, loads in the reply and
    opens full screen on a tap."""
    page, errors = app
    temp = bridge["data"] / "Temp"
    assert temp.is_dir()
    (temp / "Calories and weight.png").write_bytes(png(800, 400, (200, 80, 40)))
    await page.evaluate(FAKE_CHAT)
    await page.evaluate("(t) => { S.conv.messages[1].text = t; renderAll(); }",
                        f"Here's the plot:\n\n![Calories and weight]({temp.resolve()}/Calories and weight.png)")
    await page.wait_for_function("$$('#messages .fig').length === 1 && !$('#messages .fig.loading')")
    assert await page.evaluate("[$('#messages .fig').classList.contains('broken'), $('#messages .fig img').naturalWidth, "
                               "$('#messages .md').textContent.includes('![')]") == [False, 800, False]
    await page.click("#messages .fig img")
    await page.wait_for_selector("#mediaView", state="visible")
    assert await page.evaluate("$('#mediaFoot .figcap').textContent") == "Calories and weight"
    await page.click("#mediaClose")
    await page.wait_for_selector("#mediaView", state="hidden")
    assert errors == []


@pytest.mark.e2e
async def test_the_reported_temp_plot_reply_loads_from_the_bridge(bridge, app):
    """#77: the exact reply from the report, `![alt](</full path with spaces/in Temp.png>)`, asks the bridge's own
    /api/picture (token in the URL, as an <img> has no header) for the Temp beside the Library, and the picture loads.
    On the phone it showed broken only because the running bridge predated the route (#76 needed a restart)."""
    page, errors = app
    temp = (bridge["data"] / "Temp").resolve()
    (temp / "Calories and weight.png").write_bytes(png(800, 400, (30, 120, 110)))   # same size as #76's, which the page may keep
    await page.evaluate(FAKE_CHAT)
    await page.evaluate("(t) => { S.conv.messages[1].text = t; renderAll(); }",
                        "Here's your plot, now from the Temp folder:\n\n"
                        f"![Calories and weight](<{temp}/Calories and weight.png>)\n\n"
                        "Your weight is down from 184 to 182.6 pounds.")
    await page.wait_for_function("$$('#messages .fig').length === 1 && !$('#messages .fig.loading')")
    got = await page.evaluate("""() => { const f = $('#messages .fig'), i = f.querySelector('img'), u = new URL(i.src);
      return [f.classList.contains('broken'), i.naturalWidth, u.pathname, u.searchParams.get('path'), !!u.searchParams.get('token'),
              f.querySelector('.figcap').textContent, i.src]; }""")
    assert got[:-1] == [False, 800, "/api/picture", f"{temp}/Calories and weight.png", True, "Calories and weight"]
    # the bridge answers that URL as it is, with no header (the page may have the picture cached from #76's test)
    r = httpx.get(got[-1], timeout=10)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
    assert errors == []


@pytest.mark.e2e
async def test_chat_follows_a_picture_that_loads_late_unless_scrolled_up(bridge):
    """#67: a picture takes its height only when it loads, after the last follow, so the end of the reply stayed under
    the message box. At the end, the chat goes to the end again once it loads; scrolled up, it stays where you are."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, service_workers="block")   # WebKit routes miss what a service worker fetches
        try:
            await late_picture(page)
        finally:
            await b.close()
        assert errors == []


@pytest.mark.e2e
async def test_chat_keeps_following_when_a_picture_drops_out_for_a_frame(bridge):
    """#71: on iOS a rebuilt picture is 0 px high for a frame while it decodes again. The list got shorter, the chat
    was pulled down to the new end, and iOS sent that as a scroll up a frame later, when the picture was back: the chat
    stopped following and the end of the reply stayed under the message box. The same steps, in WebKit."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p, service_workers="block")
        try:
            filler = [m for i in range(12) for m in ({"role": "user", "text": f"Question {i}"},
                                                     {"role": "assistant", "text": f"Answer {i}. " * 30, "tools": [],
                                                      "notes": []})]
            await page.evaluate(FAKE_CHAT)
            await page.evaluate("""(f) => { S.conv.messages = [...f, { role: 'user', text: 'Plot it' },
                { role: 'assistant', text: 'Here is the plot.', tools: [], notes: [] }]; renderMessages(true); }""", filler)
            gap = "(() => { const s = $('#chatScroll'); return s.scrollHeight - s.scrollTop - s.clientHeight; })()"
            await page.evaluate("""() => { const d = document.createElement('div'); d.id = 'pic'; d.style.height = '300px';
                [...document.querySelectorAll('#messages .msg.assistant')].pop().append(d); }""")
            await page.wait_for_function(f"{gap} < 2", polling=50)
            await page.wait_for_timeout(600)   # the glide ends
            assert await page.evaluate("Follow.on")
            # In one frame the picture is gone (the chat is pulled down to the new end); before the next it is back.
            await page.evaluate("""() => new Promise((ok) => requestAnimationFrame(() => {
                $('#pic').style.height = '0px';
                void $('#chatScroll').scrollTop;   // layout: the end moves up and pulls the chat with it
                setTimeout(() => { $('#pic').style.height = '300px'; ok(); });
            }))""")
            await page.wait_for_timeout(800)
            assert await page.evaluate("Follow.on")
            assert await page.evaluate(gap) < 2   # the whole picture and the text show above the message box
        finally:
            await b.close()
        assert errors == []


async def late_picture(page):
    held = {}

    async def hold(route):
        held[route.request.url.rsplit("/", 1)[-1]] = route   # answered later: the picture "loads late"
    await page.route("https://example.com/late-*.png", hold)
    filler = [m for i in range(12) for m in ({"role": "user", "text": f"Question {i}"},
                                             {"role": "assistant", "text": f"Answer {i}. " * 30, "tools": [], "notes": []})]
    gap = "(() => { const s = $('#chatScroll'); return s.scrollHeight - s.scrollTop - s.clientHeight; })()"
    try:
        for name, up in [("late-1.png", False), ("late-2.png", True)]:
            await page.evaluate(FAKE_CHAT)
            await page.evaluate("""([f, n]) => { S.conv.messages = [...f, { role: 'user', text: 'Plot it' },
                { role: 'assistant', text: `Here:\\n\\n![Plot](https://example.com/${n})\\n\\nDone.`, tools: [], notes: [] }];
                renderMessages(true); }""", [filler, name])
            for _ in range(100):
                if name in held:
                    break
                await page.wait_for_timeout(50)
            assert name in held
            assert await page.evaluate(gap) < 2 and await page.evaluate("Follow.on")
            if up:   # the user scrolls up a little (the picture stays near the screen, so it still loads)
                await page.evaluate("$('#chatScroll').scrollTop -= 150")
                await page.wait_for_function("!Follow.on")
            top = await page.evaluate("$('#chatScroll').scrollTop")
            await held[name].fulfill(status=200, content_type="image/png", body=png(600, 900))
            await page.wait_for_function("$('#messages .fig') && !$('#messages .fig.loading')")
            assert await page.evaluate("$('#messages .fig img').getBoundingClientRect().height") > 200   # it grew the chat
            await page.wait_for_timeout(600)   # the glide ends
            if up:
                assert await page.evaluate("$('#chatScroll').scrollTop") == top and await page.evaluate(gap) > 200
            else:
                assert await page.evaluate(gap) < 2   # the whole picture and "Done." show above the message box
                assert await page.evaluate("$('#messages .fig img').getBoundingClientRect().bottom") <= \
                    await page.evaluate("$('#composer').getBoundingClientRect().top")
    finally:
        await page.unroute("https://example.com/late-*.png")
