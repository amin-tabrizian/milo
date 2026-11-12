"""LaTeX math in Milo's replies (web/app.js tex, mathBlocks, inlineMath; web/vendor/katex; style.css .math).

Unit: md() runs in node, cut from app.js (as in test_rich_tables.py), with the vendored KaTeX or without it (the app
before KaTeX has loaded). e2e: the real app in WebKit at iPhone 15 Pro size, KaTeX loaded from the bridge.
"""

import json
import re
import shutil
import subprocess

import pytest
from playwright.async_api import async_playwright

from conftest import ROOT
from test_rich_tables import RUNNER

APP = ROOT / "web" / "app.js"
KATEX = ROOT / "web" / "vendor" / "katex"
# the same cut of app.js, with window.katex set from the vendored copy when argv[2] is given
MATH_RUNNER = RUNNER.replace(
    "({}, undefined, {})", "(process.argv[2] ? { katex: require(process.argv[2]) } : {}, undefined, {})")


def md(*cases, katex=True):
    """md(text, live) for each (text, live) case, through node."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    args = ["node", "-e", MATH_RUNNER, str(APP)] + ([str(KATEX / "katex.min.js")] if katex else [])
    r = subprocess.run(args, input=json.dumps(cases), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def one(text, live=False, katex=True):
    return md([text, live], katex=katex)[0]


def maths(h):
    """The math spans: (classes, inner html)."""
    return re.findall(r'<span class="(math[^"]*)"[^>]*>', h)


def plain(h):
    """The text on screen (without the hidden MathML's TeX annotation)."""
    return re.sub(r"<[^>]+>", "", re.sub(r"<annotation[\s\S]*?</annotation>", "", h))


def test_vendored_offline():
    """KaTeX is served by the bridge itself: no CDN, the fonts are local woff2."""
    assert (KATEX / "katex.min.js").exists() and (KATEX / "LICENSE").exists()
    css = (KATEX / "katex.min.css").read_text()
    fonts = re.findall(r"url\(([^)]+)\)", css)
    assert fonts and all(f.startswith("fonts/") and f.endswith(".woff2") for f in fonts)
    assert all((KATEX / f).exists() for f in fonts)
    loader = re.search(r"function mathLoad\(\)[\s\S]*?\n}", APP.read_text()).group(0)
    assert "/vendor/katex/katex.min.js" in loader and "//" not in re.sub(r"//.*", "", loader).replace("'/vendor", "")


def test_inline_dollar_and_paren():
    a, b = md(["Area is $\\pi r^2$ here.", False], ["Area is \\(\\pi r^2\\) here.", False])
    for h in (a, b):
        assert maths(h) == ["math"] and 'class="katex"' in h and "<math" in h   # MathML too, for VoiceOver
        assert h.startswith("<p>Area is ") and h.endswith(" here.</p>")
        assert "$" not in plain(h).replace("\\", "")


def test_display_forms():
    for text in ["Sum:\n$$\\sum_{i=1}^n i = \\frac{n(n+1)}{2}$$\nDone.",
                 "Sum:\n\n$$\n\\sum_{i=1}^n i\n= \\frac{n(n+1)}{2}\n$$\n\nDone.",
                 "Sum:\n\\[\n\\sum_{i=1}^n i = \\frac{n(n+1)}{2}\n\\]\nDone.",
                 "Sum:\n```math\n\\sum_{i=1}^n i = \\frac{n(n+1)}{2}\n```\nDone."]:
        h = one(text)
        assert maths(h) == ["math display"], (text, h)
        assert 'class="katex-display"' in h and "<br><span" not in h and "</span><br>" not in h, h
        assert "Done." in h and "$" not in plain(h)


def test_environments():
    for env in ["align*", "align", "pmatrix", "bmatrix", "cases", "gather"]:
        body = "x &= 1 \\\\ y &= 2" if env.startswith(("align", "gather")) else "a & b \\\\ c & d"
        if env == "gather":
            body = "x = 1 \\\\ y = 2"
        bare = one(f"Here:\n\\begin{{{env}}}\n{body}\n\\end{{{env}}}\nafter")
        wrapped = one(f"Here:\n$$\n\\begin{{{env}}}\n{body}\n\\end{{{env}}}\n$$")
        for h in (bare, wrapped):
            assert maths(h) == ["math display"], (env, h)
            assert "\\begin" not in plain(h) and "bad" not in h, (env, h)
    inline = one("$A = \\begin{pmatrix}1 & 2\\\\3 & 4\\end{pmatrix}$ and $f(x)=\\begin{cases}1 & x>0\\\\0\\end{cases}$")
    assert maths(inline) == ["math", "math"] and "bad" not in inline


def test_dollar_amounts_stay_text():
    texts = ["It costs $5 and $10 later.", "Plans: $5-$10 a month.", "$5, $10 or $20", "Pay $1,000 now.",
             "Between $1.5M and $2M.", "Save $5 (was $8).", "Costs 5$ or 6$.", "Escaped \\$x\\$ stays.", "$ 5 $",
             "From $20/month to $200/year."]
    for t, h in zip(texts, md(*[[t, False] for t in texts])):
        assert "math" not in h, (t, h)
    assert plain(one("Escaped \\$x\\$ stays.")) == "Escaped $x$ stays."
    h = one("It costs $5, and $x^2$ is math.")
    assert maths(h) == ["math"] and plain(h).startswith("It costs $5, and ")


def test_math_inside_bold_lists_tables_headings_and_quotes():
    h = one("**Energy is $E = mc^2$ here** and *$a_1$*")
    assert re.search(r"<strong>Energy is <span class=\"math\">.*</span> here</strong>", h) and "<em><span class=\"math\">" in h
    h = one("- first $x_1 * y_1$\n- second \\(a_b\\)\n  $$\n  z^2\n  $$\n- third")
    assert h.count("<li>") == 3 and maths(h) == ["math", "math", "math display"], h
    assert "<em>" not in h   # the * and _ inside math are not emphasis
    h = one("| Term | Formula |\n|---|---|\n| Mean | $\\bar x = \\frac{1}{n}\\sum x_i$ |\n| Abs | $|x|$ |\n| Price | $5 |")
    tds = re.findall(r"<td[^>]*>(.*?)</td>", h)
    assert len(tds) == 6 and 'class="math"' in tds[1] and 'class="math"' in tds[3] and plain(tds[5]) == "$5", tds
    assert maths(one("## The $\\alpha$ case")) == ["math"]
    assert maths(one("> Quote $$\\int_0^1 x\\,dx$$")) == ["math display"]


def test_code_is_not_math():
    h = one("Use `$x$` or `$$y$$` in markdown.\n\n```\n$$z$$\n```")
    assert "math" not in h and "<code>$x$</code>" in h and "<code>$$y$$</code>" in h


def test_bad_latex_shows_as_written():
    h = one("Oops $\\frac{1}{$ and $\\notacommand{x}$ then $$\\begin{align} x \\end{matrix}$$ ok $y$")
    assert len(re.findall(r'class="math[^"]* bad"', h)) == 3, h
    assert "$\\frac{1}{$" in plain(h) and "\\notacommand{x}" in plain(h)
    assert 'ok <span class="math"><span class="katex">' in h   # what follows still renders


def test_html_in_math_is_escaped():
    for k in (True, False):
        h = one("$<img src=x onerror=alert(1)>$ and \\(<b>x</b>\\)", katex=k)
        assert "<img" not in h and "<b>" not in h, h


def test_before_katex_loads_the_latex_shows_and_waits():
    h = one("A $x^2$ and\n$$\ny\n$$", katex=False)
    assert maths(h) == ["math wait", "math display wait"], h
    assert 'data-tex="x^2"' in h and 'data-raw="$x^2$"' in h and "$x^2$" in plain(h)


def test_streaming_block_keeps_its_place():
    """A display block still streaming in shows an empty slot, never half-written LaTeX that jumps into math."""
    text = "Result:\n\n$$\n\\begin{aligned} a &= b + c \\\\ d &= e \\end{aligned}\n$$\n\nDone."
    start = text.index("$$")
    steps = md(*[[text[:n], True] for n in range(start + 2, len(text) - 6)])
    for n, h in zip(range(start + 2, len(text) - 6), steps):
        assert "\\begin" not in plain(h) and "$$" not in plain(h), (text[:n], h)
        assert "math display" in h, (text[:n], h)
    h = one("Then\n\\begin{align}\nx &= 1", live=True)
    assert "math display pending" in h and "\\begin" not in plain(h)
    h = one("So $a * b$ and", live=True)   # the streaming tail does not close the * inside math as italics
    assert maths(h) == ["math"] and not plain(h).endswith("*"), h
    h = one("Pay $5 and", live=True)
    assert plain(h).startswith("Pay $5 and") and "math" not in h


# e2e: the app in WebKit at iPhone size


from test_bridge_e2e import FAKE_CHAT, bridge, phone_page  # noqa: E402,F401  (the test bridge, own port and data)

REPLY = ("Inline $e^{i\\pi} + 1 = 0$ costs $5 and $10.\n\n"
         "$$\n\\begin{aligned} f(x) &= \\sum_{n=0}^{\\infty} \\frac{f^{(n)}(a)}{n!}(x-a)^n "
         "+ \\int_a^b g(t)\\,dt + \\prod_{k=1}^{m} \\left(1 + \\frac{1}{k^2}\\right) + \\cdots \\end{aligned}\n$$\n\n"
         "| x | $x^2$ |\n|---|---|\n| 3 | $9$ |\n\nBad: $\\frac{1}{$ end.")


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_math_renders_offline_and_wide_formula_scrolls_inside(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        outside = []
        page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(("http://127.0.0.1", "http://localhost", "data:")) else None)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""(t) => { S.conv.messages.push({ role: 'user', text: 'Math' },
            { role: 'assistant', text: t, tools: [], notes: [] }); renderMessages(true); }""", REPLY)
        bub = page.locator(".msg.assistant .bubble").last
        await bub.locator(".math .katex").first.wait_for(timeout=10000)
        await page.wait_for_function("() => !document.querySelector('.math.wait')", timeout=10000)
        m = await bub.evaluate("""(b) => {
            const d = b.querySelector('.math.display'), r = d.getBoundingClientRect(), br = b.getBoundingClientRect();
            const font = getComputedStyle(b.querySelector('.katex .mord, .katex .mathnormal') || b).fontFamily;
            return { n: b.querySelectorAll('.math .katex').length, bad: b.querySelectorAll('.math.bad').length,
              inside: r.left >= br.left - 0.5 && r.right <= br.right + 0.5, scrolls: d.scrollWidth > d.clientWidth + 10,
              pageWide: document.documentElement.scrollWidth > innerWidth, chatWide: $('#chatScroll').scrollWidth > $('#chatScroll').clientWidth,
              font, text: b.innerText, table: !!b.querySelector('td .math .katex'), fonts: [...document.fonts].filter((f) => f.status === 'loaded' && /KaTeX/.test(f.family)).length }; }""")
        assert m["n"] == 4 and m["bad"] == 1 and m["table"], m
        assert m["inside"] and m["scrolls"] and not m["pageWide"] and not m["chatWide"], m
        assert "KaTeX" in m["font"] and m["fonts"] > 0, m
        assert "costs $5 and $10." in m["text"] and "\\frac{1}{" in m["text"], m
        assert outside == [] and errors == [], (outside, errors)
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_streaming_math_never_shows_raw_block_latex(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("() => new Promise((ok) => { mathLoad(); MATH.load.then(ok); })")
        await page.evaluate("""() => { S.conv.messages.push({ role: 'user', text: 'Math' },
            { role: 'assistant', text: '', tools: [], notes: [] }); curConv().running = true; renderMessages(true); }""")
        text = "Here:\n\n$$\n\\begin{aligned} a &= b + c \\\\ d &= e \\end{aligned}\n$$\n\nDone."
        start = text.index("$$")
        seen = await page.evaluate("""([text, start]) => {
            const m = S.conv.messages.at(-1), seen = [];
            for (let n = start + 2; n <= text.length; n++) {
              m.text = text.slice(0, n); renderMessages();
              const bub = document.querySelector('.msg.assistant:last-child .bubble');
              seen.push({ n, raw: /\\\\begin|\\$\\$/.test(bub?.innerText || ''), slot: !!bub?.querySelector('.math.display') });
            }
            return seen;
          }""", [text, start])
        assert not any(s["raw"] for s in seen), [s for s in seen if s["raw"]][:3]
        assert all(s["slot"] for s in seen if s["n"] < len(text) - 6), [s for s in seen if not s["slot"]][:3]
        assert errors == []
        await b.close()
