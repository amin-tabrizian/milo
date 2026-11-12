"""Rich text in Milo's replies (web/app.js md, emph, inline, fenceParts, mdTail, listHtml, codeBlock; style.css .md).

Unit: md() runs in node, cut from app.js (same runner as the table tests). e2e: the real app in WebKit at iPhone 15 Pro size.
"""

import re

import pytest
from playwright.async_api import async_playwright

from conftest import ROOT
from test_rich_tables import md


def text_of(html):
    return re.sub(r"<[^>]+>", "", html)


def test_emphasis_and_words_that_only_look_like_it():
    b, i, bi, s, u, plain = md(["**bold** and __too__", False], ["*it* and _it_", False], ["***both***", False],
                               ["~~gone~~", False], ["snake_case_name and 2 * 3 * 4", False], ["a ** b", False])
    assert b == "<p><strong>bold</strong> and <strong>too</strong></p>"
    assert i == "<p><em>it</em> and <em>it</em></p>"
    assert bi == "<p><strong><em>both</em></strong></p>"
    assert s == "<p><del>gone</del></p>"
    assert u == "<p>snake_case_name and 2 * 3 * 4</p>"
    assert plain == "<p>a ** b</p>"
    [nested] = md(["**bold with *italic* inside**", False])
    assert nested == "<p><strong>bold with <em>italic</em> inside</strong></p>"


def test_headings_all_levels_and_closing_hashes():
    hs = md(*[["#" * n + " Title ##", False] for n in range(1, 7)], ["####### seven", False])
    for n, h in enumerate(hs[:6], 1):
        assert h == f"<h{min(n + 1, 6)}>Title</h{min(n + 1, 6)}>", h
    assert "<h" not in hs[6]


def test_nested_ordered_and_task_lists():
    nested, start, tasks = md(["- a\n  - b\n    - c\n- d", False], ["3. three\n4. four", False],
                              ["- [ ] todo\n- [x] done", False])
    assert nested == "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>"
    assert start == '<ol start="3"><li>three</li><li>four</li></ol>'
    assert re.fullmatch(r'<ul><li class="task"><input type="checkbox" disabled> ?todo</li>'
                        r'<li class="task"><input type="checkbox" disabled checked> ?done</li></ul>', tasks), tasks


def test_blockquote_rule_and_line_breaks():
    q, hr, br = md(["> one\n> - item\n\nafter", False], ["a\n\n---\n\nb", False], ["line one\nline two", False])
    assert q.startswith("<blockquote>") and "<li>item</li>" in q and q.endswith("<p>after</p>")
    assert "<hr>" in hr and "<li" not in hr
    assert br == "<p>line one<br>line two</p>"


def test_links_open_safely_and_bad_schemes_stay_text():
    lk, bare, bad, wiki = md(["see [docs](https://x.com/a_b_c)", False], ["go to https://x.com/a_b.", False],
                             ["[x](javascript:alert(1)) <script>", False], ["https://en.wikipedia.org/wiki/Foo_(bar)", False])
    assert '<a href="https://x.com/a_b_c" target="_blank" rel="noopener noreferrer">docs</a>' in lk
    assert 'href="https://x.com/a_b"' in bare and bare.endswith("</a>.</p>")
    assert "<a" not in bad and "<script>" not in bad and "&lt;script&gt;" in bad
    assert 'href="https://en.wikipedia.org/wiki/Foo_(bar)"' in wiki
    [paren] = md(["(see https://x.com/a).", False])
    assert 'href="https://x.com/a"' in paren and paren.endswith("</a>).</p>")


def test_code_spans_escapes_and_fences():
    span, dbl, esc_, mid = md(["use `a*b*c` here", False], ["``a ` b``", False], [r"\*not em\*", False],
                              ["say ```hi``` ok", False])
    assert span == "<p>use <code>a*b*c</code> here</p>"
    assert dbl == "<p><code>a ` b</code></p>"
    assert esc_ == "<p>*not em*</p>"
    assert '<div class="code">' not in mid
    [block, tilde] = md(["```Python\nx = '<b>' # **no**\n```\nafter", False], ["~~~\nplain\n~~~", False])
    assert block.startswith('<div class="code"><div class="code-bar"><span>python</span><button class="code-copy"')
    assert "&lt;b&gt;" in block and "<strong>" not in block and block.endswith("<p>after</p>")
    assert "<pre><code>plain</code></pre>" in tilde


def test_streaming_never_shows_raw_markers():
    """Each prefix of a reply streaming in renders without stray **, `, [ or ]( and without empty markers."""
    text = ("## Plan\n\nSome **bold words** and *it* and `code here` and [the docs](https://x.com/d) "
            "plus ~~old~~.\n\n- one\n- **two**\n\n> quoted\n\nEnd.")
    steps = md(*[[text[:n], True] for n in range(1, len(text) + 1)])
    for n, h in enumerate(steps, 1):
        t = text_of(h)
        assert not re.search(r"\*|`|\[|\]\(|~~|^#", t), (text[:n], h)
    [open_fence] = md(["```js\nlet a = 1", True])
    assert '<div class="code">' in open_fence and "let a = 1" in open_fence


# e2e: the app in WebKit at iPhone size


from test_bridge_e2e import FAKE_CHAT, bridge, phone_page  # noqa: E402,F401  (the test bridge, own port and data)

RICH = ("## Title\n\n**Bold**, *it*, ~~del~~, `inline`.\n\n- a\n  - nested\n- [x] done\n\n> quote\n\n---\n\n"
        "See [docs](https://example.com/docs) or https://example.com/" + "a" * 120 + "\n\n"
        "```python\ndef f(x):\n    return x + 1  # " + "long_" * 40 + "\n```")


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_rich_reply_renders_highlights_copies_and_fits_the_phone(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""(t) => { S.conv.messages.push({ role: 'user', text: 'Show me' },
            { role: 'assistant', text: t, tools: [], notes: [] }); renderMessages(true); }""", RICH)
        await page.wait_for_function("document.querySelector('.msg.assistant:last-child .code code span[class^=hljs-]')")
        m = await page.evaluate("""() => { const bub = document.querySelector('.msg.assistant:last-child .bubble');
            const a = bub.querySelector('a'), sc = $('#chatScroll');
            return { h3: !!bub.querySelector('h3'), strong: !!bub.querySelector('strong'), del: !!bub.querySelector('del'),
              nested: !!bub.querySelector('li > ul'), task: !!bub.querySelector('li.task input[checked]'), hr: !!bub.querySelector('hr'),
              quote: !!bub.querySelector('blockquote'), target: a.target, rel: a.rel,
              wide: sc.scrollWidth > sc.clientWidth || document.documentElement.scrollWidth > innerWidth,
              preWide: bub.querySelector('pre').scrollWidth > bub.querySelector('pre').clientWidth + 1,
              kw: getComputedStyle(bub.querySelector('.hljs-keyword')).color, plain: getComputedStyle(bub.querySelector('pre code')).color }; }""")
        assert all(m[k] for k in ("h3", "strong", "del", "nested", "task", "hr", "quote")), m
        assert m["target"] == "_blank" and "noopener" in m["rel"], m
        assert not m["wide"] and not m["preWide"], m
        assert m["kw"] != m["plain"], m
        await page.evaluate("""() => { window.copied = null;
            Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: (t) => { window.copied = t; return Promise.resolve(); } } }); }""")
        await page.locator(".msg.assistant:last-child .code-copy").click()
        await page.wait_for_function("window.copied !== null")
        assert (await page.evaluate("window.copied")).startswith("def f(x):\n    return x + 1")
        await page.wait_for_function("/Copied/.test(document.body.innerText)")
        assert errors == []
        await b.close()


@pytest.mark.e2e
@pytest.mark.asyncio(loop_scope="module")
async def test_streaming_rich_text_shows_no_raw_markers_and_keeps_earlier_messages(bridge):
    async with async_playwright() as p:
        b, page, errors = await phone_page(p)
        await page.evaluate(FAKE_CHAT)
        await page.evaluate("""() => { S.conv.messages.push({ role: 'user', text: 'Go' },
            { role: 'assistant', text: '', tools: [], notes: [] }); curConv().running = true; renderMessages(true); }""")
        text = "Some **bold words**, `code`, and [a link](https://example.com).\n\n- one\n- *two*\n\n```js\nlet a = 1;\n```\nDone."
        bad = await page.evaluate("""(text) => {
            const first = document.querySelector('.msg'), m = S.conv.messages.at(-1), bad = [];
            for (let n = 1; n <= text.length; n++) {
              m.text = text.slice(0, n); renderMessages();
              const bub = document.querySelector('.msg.assistant:last-child .bubble');
              const t = [...bub.childNodes].length ? bub.cloneNode(true) : bub;
              t.querySelectorAll('pre').forEach((p) => p.remove());
              if (/\\*|`|\\[|\\]\\(/.test(t.textContent)) bad.push(text.slice(0, n));
            }
            if (document.querySelector('.msg') !== first) bad.push('first message rebuilt');
            return bad; }""", text)
        assert bad == [], bad[:3]
        assert errors == []
        await b.close()
