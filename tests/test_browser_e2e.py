"""Real headless Chrome + Playwright MCP against the local test site. No AI model: the test plays the agent.

Run with:  uv run pytest -m e2e
"""

import asyncio
import re
import uuid

import pytest
import pytest_asyncio
from mcp import types

from browser import BrowserManager
from browser_mcp import WAITED_NOTE, BrowserTools
from conftest import TEST_PASSWORD
from vault import Vault

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]


class Recorder:
    def __init__(self):
        self.answer = "allow_once"
        self.approvals, self.records, self.notes = [], [], []

    async def approve(self, conv, title, detail, options):
        self.approvals.append(title)
        return self.answer

    def record(self, *args, **kwargs):
        self.records.append(args)

    async def notify(self, title, body, conv):
        self.notes.append(body)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def rig(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("browser")
    browser = BrowserManager(tmp / "profile", port=9444, headless=True)
    vault = Vault(tmp / "accounts.json", service=f"Milo-e2e-{uuid.uuid4().hex[:8]}")
    rec = Recorder()
    tools = BrowserTools(browser, vault, key="k", approve=rec.approve, record=rec.record, notify=rec.notify,
                         conv_for=lambda k: "c1")
    await browser.start()
    await tools.start_upstream()
    yield browser, tools, vault, rec
    for acct in vault.accounts():
        vault.delete(acct["id"])
    await tools.stop_upstream()
    await browser.stop(close_chrome=True)


@pytest.fixture(autouse=True)
def fresh(rig):
    browser, tools, vault, rec = rig
    rec.answer = "allow_once"
    rec.approvals.clear(), rec.records.clear(), rec.notes.clear()
    tools.forget_task("c1")
    yield


def text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


def ref(snapshot: str, role: str, name: str) -> str:
    m = re.search(rf'{role} "{re.escape(name)}"[^\n]*\[ref=(\w+)\]', snapshot)
    assert m, f'{role} "{name}" not in snapshot:\n{snapshot[:1500]}'
    return m.group(1)


async def open_page(tools, url) -> str:
    r = await tools.call("c1", "browser_navigate", {"url": url})
    assert not r.is_error, text(r)
    return text(await tools.call("c1", "browser_snapshot", {}))


async def page_for(browser, part):
    for _ in range(20):
        for p in browser.pages():
            if part in p.url:
                return p
        await asyncio.sleep(0.1)
    raise AssertionError(f"no page with {part}")


async def test_navigate_snapshot_and_activity(rig, site_url):
    browser, tools, _, rec = rig
    snap = await open_page(tools, f"{site_url}/index.html")
    assert "Milo Test Site" in snap
    assert any(r[1].startswith("Open http://127.0.0.1") for r in rec.records)
    assert browser.state()["url"].endswith("/index.html")


async def test_safe_click_needs_no_approval(rig, site_url):
    browser, tools, _, rec = rig
    snap = await open_page(tools, f"{site_url}/shop.html")
    r = await tools.call("c1", "browser_click", {"element": "Add to wishlist button",
                                                 "target": ref(snap, "button", "Add to wishlist")})
    assert not r.is_error and rec.approvals == []
    page = await page_for(browser, "shop.html")
    assert await page.text_content("#wished") == "1"


async def test_risky_click_denied_changes_nothing(rig, site_url):
    browser, tools, _, rec = rig
    snap = await open_page(tools, f"{site_url}/shop.html")
    rec.answer = "reject_once"
    r = await tools.call("c1", "browser_click", {"element": "Buy now button", "target": ref(snap, "button", "Buy now")})
    assert r.is_error and len(rec.approvals) == 1 and "Buy now" in rec.approvals[0]
    assert await (await page_for(browser, "shop.html")).text_content("#bought") == "0"


async def test_allow_on_this_site_covers_later_clicks(rig, site_url):
    browser, tools, _, rec = rig
    snap = await open_page(tools, f"{site_url}/shop.html")
    rec.answer = "allow_site"
    buy = ref(snap, "button", "Buy now")
    await tools.call("c1", "browser_click", {"element": "Buy now button", "target": buy})
    await tools.call("c1", "browser_click", {"element": "Buy now button", "target": buy})
    assert len(rec.approvals) == 1
    assert await (await page_for(browser, "shop.html")).text_content("#bought") == "2"


async def test_saved_login_without_exposing_the_password(rig, site_url):
    browser, tools, vault, rec = rig
    acct = vault.add(domain="127.0.0.1", username="tester", password=TEST_PASSWORD)
    snap = await open_page(tools, f"{site_url}/login.html")
    await tools.call("c1", "browser_click", {"element": "Username textbox", "target": ref(snap, "textbox", "Username")})
    r1 = await tools.call("c1", "browser_fill_credential", {"account_id": acct["id"], "field": "username"})
    await tools.call("c1", "browser_click", {"element": "Password textbox", "target": ref(snap, "textbox", "Password")})
    r2 = await tools.call("c1", "browser_fill_credential", {"account_id": acct["id"], "field": "password"})
    assert not r1.is_error and not r2.is_error, text(r1) + text(r2)
    assert rec.approvals == ["Log in to 127.0.0.1 as tester?"]       # asked once for the whole login
    r3 = await tools.call("c1", "browser_click", {"element": "Log in button", "target": ref(snap, "button", "Log in")})
    page = await page_for(browser, "login.html")
    assert await page.text_content("#status") == "Welcome, tester"
    seen = text(r1) + text(r2) + text(r3) + text(await tools.call("c1", "browser_snapshot", {})) + str(rec.records)
    assert TEST_PASSWORD not in seen


async def test_login_refused_on_the_wrong_site(rig, site_url):
    browser, tools, vault, rec = rig
    acct = vault.add(domain="example.com", username="tester", password="wrong-site-secret")
    snap = await open_page(tools, f"{site_url}/login.html")
    await tools.call("c1", "browser_click", {"element": "Password textbox", "target": ref(snap, "textbox", "Password")})
    r = await tools.call("c1", "browser_fill_credential", {"account_id": acct["id"], "field": "password"})
    assert r.is_error and "Refused" in text(r) and rec.approvals == []
    assert await (await page_for(browser, "login.html")).input_value("#password") == ""


async def test_tool_calls_wait_during_takeover(rig, site_url):
    browser, tools, _, _ = rig
    await browser.take("testing")
    task = asyncio.create_task(tools.call("c1", "browser_navigate", {"url": f"{site_url}/index.html"}))
    await asyncio.sleep(0.5)
    assert not task.done()
    await browser.release()
    assert text(await asyncio.wait_for(task, 30)).startswith(WAITED_NOTE)


async def test_live_view_frames_and_user_input(rig, site_url):
    browser, tools, _, _ = rig
    await open_page(tools, f"{site_url}/shop.html")
    page = await page_for(browser, "shop.html")
    await browser._activate(page)
    before = int(await page.text_content("#wished"))
    q = await browser.add_viewer()
    frames = 0

    async def collect():
        nonlocal frames
        while True:
            if isinstance(await q.get(), bytes):
                frames += 1

    collector = asyncio.create_task(collect())
    await browser.take()
    box = await page.locator("#wish").bounding_box()
    for _ in range(3):   # what three phone taps send: CSS-pixel coordinates of the page
        await browser.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await asyncio.sleep(0.4)
    await browser.release()
    collector.cancel()
    await browser.remove_viewer(q)
    assert frames >= 3            # the first screenshot plus repaints after each tap
    assert int(await page.text_content("#wished")) == before + 3


async def test_tabs_milo_opened_close_when_it_is_idle(rig, site_url, monkeypatch):
    """Tabs that open while Milo works (an Apply link that opens a new tab, browser_tabs new) close once it is idle;
    the tab on show and a tab the user opened stay (2026-10-21: 37 Chrome processes held 9 GB). The tools still work."""
    browser, tools, _, _ = rig
    await open_page(tools, f"{site_url}/index.html")
    users = await browser.browser.contexts[0].new_page()   # opened while Milo was idle
    await users.goto(f"{site_url}/shop.html")
    working = True
    monkeypatch.setattr(browser, "working", lambda: working)
    try:
        snap = await open_page(tools, f"{site_url}/links.html")
        r = await tools.call("c1", "browser_click", {"element": "Apply link", "target": ref(snap, "link", "Apply")})
        assert not r.is_error, text(r)
        popup = await page_for(browser, "login.html")
        r = await tools.call("c1", "browser_tabs", {"action": "new"})
        assert not r.is_error, text(r)
        await browser.show(await page_for(browser, "links.html"))
        before = len(browser.pages())
        await browser.release_lock("c1")
        working = False
        assert await browser.close_milos_tabs() == 2
        assert popup.is_closed() and len(browser.pages()) == before - 2
        assert not users.is_closed() and browser.page.url.endswith("links.html")
        assert await browser.close_milos_tabs() == 0
        await tools.select_shown()   # Playwright MCP's tab (the new one) closed: it goes on in the tab on show
        await open_page(tools, f"{site_url}/check.html")
        assert browser.page.url.endswith("check.html") and users.url.endswith("shop.html")
    finally:
        await users.close()


async def test_uploads_come_only_from_the_files_folder(rig, site_url, tmp_path):
    browser, _, vault, rec = rig
    library = tmp_path / "Library"
    library.mkdir()
    (library / "resume.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "secret.txt").write_text("not for the web")
    tools = BrowserTools(browser, vault, key="k", approve=rec.approve, record=rec.record, notify=rec.notify,
                         conv_for=lambda k: "c1", files_dir=str(library))
    await tools.start_upstream()
    try:
        snap = await open_page(tools, f"{site_url}/upload.html")
        r = await tools.call("c1", "browser_click", {"element": "Resume file input", "target": ref(snap, "button", "Resume")})
        assert not r.is_error, text(r)
        r = await tools.call("c1", "browser_file_upload", {"paths": [str(tmp_path / "secret.txt")]})
        assert r.is_error and "outside allowed roots" in text(r), text(r)
        r = await tools.call("c1", "browser_file_upload", {"paths": [str(library / "resume.pdf")]})   # chooser still open
        assert not r.is_error, text(r)
        page = await page_for(browser, "upload.html")
        assert await page.inner_text("#picked") == "Picked resume.pdf"
        assert any("Upload 1 file(s)" in a for a in rec.approvals)   # uploads still ask the user
    finally:
        await tools.stop_upstream()


async def test_a_screenshot_for_the_user_saves_in_temp_and_shows_in_the_chat(rig, site_url, tmp_path):
    """#85: the browser could save only in the Library and milo/.playwright-mcp, which /api/picture doesn't serve, so
    a screenshot sent to the user showed broken. Its output folder is Temp now, which the app serves."""
    from features import find_picture
    browser, _, vault, rec = rig
    library, temp = tmp_path / "Library", tmp_path / "Temp"
    library.mkdir(), temp.mkdir()
    tools = BrowserTools(browser, vault, key="k", approve=rec.approve, record=rec.record, notify=rec.notify,
                         conv_for=lambda k: "c1", files_dir=str(library), output_dir=str(temp))
    await tools.start_upstream()
    try:
        await open_page(tools, f"{site_url}/check.html")
        shot = temp / "bbcnews.png"
        r = await tools.call("c1", "browser_take_screenshot", {"type": "png", "filename": str(shot)})
        assert not r.is_error, text(r)
        assert shot.read_bytes()[:4] == b"\x89PNG"
        assert find_picture(str(shot), [library, temp]) == shot.resolve()   # the roots /api/picture serves
        r = await tools.call("c1", "browser_take_screenshot", {"type": "png", "filename": str(tmp_path / "out.png")})
        assert r.is_error and "outside allowed roots" in text(r), text(r)   # still nowhere else
    finally:
        await tools.stop_upstream()


async def test_a_tab_that_does_not_answer_is_reopened(rig, site_url):
    """A user's tab that never answered Playwright hung every browser tool until goose gave up at 300 s
    (2026-10-27). Here a page busy in a loop stands in for it: it is reopened at the same address, as the user's."""
    browser, tools, _, _ = rig
    await open_page(tools, f"{site_url}/index.html")
    busy = "data:text/html,<title>Busy</title><script>const t=Date.now();while(Date.now()-t<6000){}</script>"
    cdp = await browser.browser.new_browser_cdp_session()
    async with browser.browser.contexts[0].expect_page() as opened:
        await cdp.send("Target.createTarget", {"url": busy, "background": True})
    await cdp.detach()
    stuck = await opened.value
    await asyncio.sleep(0.5)
    assert await browser.reopen_stuck_tabs(wait=1) == ["Busy"]
    assert stuck.is_closed()
    again = [p for p in browser.pages() if p.url == busy]
    assert len(again) == 1 and again[0] not in browser._milos
    await asyncio.sleep(6)                       # its loop ends; the tools still answer
    assert await browser.reopen_stuck_tabs(wait=1) == []
    await again[0].close()
    await open_page(tools, f"{site_url}/check.html")
