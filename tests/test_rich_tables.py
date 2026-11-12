"""Markdown tables in Milo's replies (web/app.js md, mdTable, tableCells; style.css .table-wrap).

Unit: md() runs in node, cut from app.js (its markdown section). e2e: the real app in WebKit at iPhone 15 Pro size.
"""

import json
import re
import shutil
import subprocess

import pytest
from playwright.async_api import async_playwright

from conftest import ROOT

APP = ROOT / "web" / "app.js"
# app.js's top-level functions and one-line constants, without the code that runs at load, so md() runs without a page
# (it calls helpers that other parts of the renderer add: math, pictures, diagrams)
RUNNER = r"""
const fs = require('fs'); const lines = fs.readFileSync(process.argv[1], 'utf8').split('\n'), code = [];
for (let i = 0; i < lines.length; i++) {
  const l = lines[i];
  if (/^const \w+ = .*;(\s*\/\/.*)?$/.test(l)) {
    const name = l.match(/^const (\w+)/)[1];
    const c = `var ${name}; try { ${l.replace(/^const /, '')}\n} catch {}`;
    try { new Function(c); code.push(c); } catch {}
  } else if (/^(async )?function /.test(l)) {
    const one = (l.match(/\{/g) || []).length === (l.match(/\}/g) || []).length;
    let j = i; if (!one) while (j < lines.length && lines[j] !== '}') j++;
    const fn = lines.slice(i, j + 1).join('\n');
    try { new Function(fn); code.push(fn); i = j; } catch {}   // a brace in a string fooled the cut: skip it
  }
}
const lib = new Function('window', 'document', 'navigator', code.join('\n') + '\nreturn { md };')({}, undefined, {});
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([t, live]) => lib.md(t, live))));
"""


def md(*cases):
    """md(text, live) for each (text, live) case, through node."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    r = subprocess.run(["node", "-e", RUNNER, str(APP)], input=json.dumps(cases), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def cells(html, tag):
    return re.findall(rf"<{tag}(?: class=\"([\w ]+)\")?>(.*?)</{tag}>", html)


def test_alignment_header_and_inline_content():
    [h] = md(["| Name | Qty | Note |\n|:---|---:|:---:|\n| **Bob** | 4 | `x` and *y* |", False])
    assert h.startswith('<div class="table-wrap"><table><thead>') and h.endswith("</table></div>")
    assert cells(h, "th") == [("", "Name"), ("r", "Qty"), ("c", "Note")]
    assert cells(h, "td") == [("", "<strong>Bob</strong>"), ("r", "4"), ("c", "<code>x</code> and <em>y</em>")]


def test_pipes_inside_code_math_and_escapes_stay_in_their_cell():
    [h] = md(["| A | B | C | D |\n|---|---|---|---|\n| `a|b` | $|x|$ | p \\| q | $$|y|$$ |", False])
    tds = [c for _, c in cells(h, "td")]
    assert len(tds) == 4 and tds[0] == "<code>a|b</code>" and tds[2] == "p | q"
    assert "x" in tds[1] and "y" in tds[3]   # the math itself is drawn by the math renderer


def test_prices_are_not_math():
    [h] = md(["| Plan | Price |\n|---|---|\n| $5 | $10 |", False])
    assert [re.sub(r"<[^>]+>", "", c) for _, c in cells(h, "td")] == ["$5", "$10"]


def test_rows_pad_to_the_header_and_tables_without_outer_pipes():
    short, bare = md(["| A | B | C |\n|---|---|---|\n| 1 |", False], ["a | b\n--- | ---\nc | d\n\nafter", False])
    assert [c for _, c in cells(short, "td")] == ["1", "", ""]
    assert [c for _, c in cells(bare, "th")] == ["a", "b"] and [c for _, c in cells(bare, "td")] == ["c", "d"]
    assert bare.endswith("<p>after</p>")


def test_not_a_table():
    plain, rule = md(["Use a | b for either.", False], ["a | b\n---", False])
    assert "<table" not in plain and "<table" not in rule


def test_streaming_table_keeps_its_shape():
    """Each step of a table streaming in is already a table: no "| a | b |" text that jumps into a grid."""
    text = "Here:\n\n| Name | Qty |\n|:---|---:|\n| Bob | 4 |\n| Al | 12 |\n\nDone."
    start = text.index("| Name")
    steps = md(*[[text[:n], True] for n in range(start + 1, len(text) - 6)])
    for n, h in zip(range(start + 1, len(text) - 6), steps):
        assert "|" not in re.sub(r"<[^>]+>", "", h).replace("Here:", ""), (text[:n], h)
        if n > start + 2:
            assert h.count("<table>") == 1, (text[:n], h)
    # a finished reply that ends on a header line with no separator is just text
    [done] = md(["Here:\n\n| Name | Qty |", False])
    assert "<table" not in done


def test_streaming_partial_row_fills_the_grid():
    [h] = md(["| A | B | C |\n|---|---|---|\n| 1 | 2", True])
    assert [c for _, c in cells(h, "td")] == ["1", "2", ""]


# e2e: the app in WebKit at iPhone size


from test_bridge_e2e import FAKE_CHAT, bridge, phone_page  # noqa: E402,F401  (the test bridge, own port and data)

WIDE = ("| " + " | ".join(f"Column {k}" for k in range(9)) + " |\n" + "|---" * 9 + "|\n"
        + "| " + " | ".join(f"**v{k}** `c{k}`" for k in range(9)) + " |\n"
        + "| A long note that should wrap inside its cell rather than make a very tall thin column | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |")


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_wide_table_scrolls_inside_the_bubble_not_the_chat(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""(t) => { S.conv.messages.push({ role: 'user', text: 'Compare' },
            { role: 'assistant', text: 'Here:\\n\\n' + t + '\\n\\nDone.', tools: [], notes: [] }); renderMessages(true); }""", WIDE)
        wrap = page.locator(".msg.assistant .table-wrap").last
        m = await wrap.evaluate("""(w) => { const b = w.closest('.bubble').getBoundingClientRect(), r = w.getBoundingClientRect();
            const th = w.querySelector('th'), td = w.querySelector('td'), long = w.querySelectorAll('tbody tr')[1].firstElementChild;
            return { inside: r.left >= b.left - 0.5 && r.right <= b.right + 0.5, scrolls: w.scrollWidth > w.clientWidth + 20,
              pageWide: document.documentElement.scrollWidth > innerWidth, chatWide: $('#chatScroll').scrollWidth > $('#chatScroll').clientWidth,
              thBg: getComputedStyle(th).backgroundColor, tdBg: getComputedStyle(td).backgroundColor, thWeight: getComputedStyle(th).fontWeight,
              longW: long.getBoundingClientRect().width, longH: long.getBoundingClientRect().height, rowH: td.getBoundingClientRect().height,
              strong: !!td.querySelector('strong'), code: !!td.querySelector('code') }; }""")
        assert m["inside"] and m["scrolls"] and not m["pageWide"] and not m["chatWide"], m
        assert m["thBg"] != m["tdBg"] and int(m["thWeight"]) >= 600, m
        assert m["strong"] and m["code"], m
        assert m["longW"] > 100 and m["longH"] < m["rowH"] * 6, m   # wraps in a readable column, not one word per line
        await wrap.evaluate("(w) => { w.scrollLeft = 120; }")
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_streaming_table_does_not_flicker_or_lose_its_scroll(bridge):
    """While a table streams in, it is a table from its first line, and a wide one stays where you scrolled it."""
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push({ role: 'user', text: 'Compare' },
            { role: 'assistant', text: '', tools: [], notes: [] }); curConv().running = true; renderMessages(true); }""")
        text = "Here:\n\n" + WIDE + "\n| more | rows | here | 4 | 5 | 6 | 7 | 8 | 9 |\n\nDone."
        start = text.index("| Column")
        seen = await page.evaluate("""([text, start]) => {
            const m = S.conv.messages.at(-1), seen = [];
            for (let n = start + 1; n <= text.length; n += 3) {
              m.text = text.slice(0, n); renderMessages();
              const bub = document.querySelector('.msg.assistant:last-child .bubble');
              const w = bub?.querySelector('.table-wrap');
              if (w && n > start + 40 && !seen.scrolled) { w.scrollLeft = 150; seen.scrolled = w.scrollLeft; }
              seen.push({ n, table: !!w, pipe: /\\|/.test((bub?.innerText || '').replace(/`[^`]*`/g, '')), left: w ? w.scrollLeft : null });
            }
            return { steps: seen, scrolled: seen.scrolled };
          }""", [text, start])
        steps = seen["steps"]
        assert seen["scrolled"] > 0
        assert all(s["table"] for s in steps if s["n"] > start + 3), [s for s in steps if not s["table"]][:3]
        assert not any(s["pipe"] for s in steps), [s for s in steps if s["pipe"]][:3]
        after = [s["left"] for s in steps if s["n"] > start + 43]
        assert after and all(abs(x - seen["scrolled"]) < 2 for x in after), after
        assert errors == []
        await b.close()
