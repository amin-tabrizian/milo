"""milo-browser server logic with a fake browser: risk gate, credentials, takeover, redaction, auth."""

import asyncio

import httpx
import pytest
from mcp import types

from browser_mcp import (EXCLUDED, EXTRA_TOOLS, WAITED_NOTE, BrowserMCPApp, BrowserTools, describe, pretty_title,
                         risk_of)


# pure helpers


@pytest.mark.parametrize("name,args,risky", [
    ("browser_click", {"element": "Buy now button"}, True),
    ("browser_click", {"element": "Place order"}, True),
    ("browser_click", {"element": "Send message"}, True),
    ("browser_click", {"element": "Delete repository button"}, True),
    ("browser_click", {"element": "Cancel my subscription link"}, True),
    ("browser_click", {"element": "Add to wishlist button"}, False),
    ("browser_click", {"element": "Search"}, False),
    ("browser_click", {"element": "Cancel"}, False),          # closing a dialog is fine
    ("browser_click", {"element": "Log in button"}, False),
    ("browser_type", {"element": "Message to seller", "text": "hi"}, False),
    ("browser_type", {"element": "Confirm password field", "text": "x"}, True),
    ("browser_file_upload", {"paths": ["/Users/a/tax.pdf"]}, True),
    ("browser_file_upload", {"paths": []}, False),
    ("browser_navigate", {"url": "https://shop.example/checkout"}, False),
])
def test_risk_table(name, args, risky):
    assert (risk_of(name, args) is not None) is risky


def test_pretty_titles_and_descriptions():
    assert pretty_title("mcp: milo-browser  browser_navigate") == "Browser: navigate"
    assert pretty_title("mcp: milo-browser  browser_fill_credential") == "Browser: fill credential"
    assert pretty_title("Terminal") == "Terminal"
    assert describe("browser_navigate", {"url": "https://a.b"}) == "Open https://a.b"
    assert describe("browser_click", {"element": "OK"}) == "Click OK"


# fakes


class FakePage:
    def __init__(self, url):
        self.url = url


class FakeBrowser:
    cdp_url = "http://127.0.0.1:1"

    def __init__(self, url="http://127.0.0.1:5000/login.html", focus="password"):
        self.page = FakePage(url)
        self.focus = focus
        self.typed: list[str] = []
        self.controller = "milo"
        self.released = asyncio.Event()
        self.released.set()
        self.owner = None

    async def ensure_running(self):
        pass

    async def acquire(self, owner):
        self.owner = owner

    async def wait_for_milo_turn(self):
        if self.released.is_set():
            return False
        await self.released.wait()
        return True

    async def take(self, reason=""):
        self.controller = "user"
        self.released.clear()

    async def release(self):
        self.controller = "milo"
        self.released.set()

    async def focused_input(self):
        return (self.page, self.focus) if self.focus else None

    async def type_secret(self, page, text):
        self.typed.append(text)

    def state(self):
        return {"url": self.page.url, "controller": self.controller}


class Recorder:
    def __init__(self, answer="allow_once"):
        self.answer = answer
        self.approvals = []
        self.records = []
        self.notes = []

    async def approve(self, conv, title, detail, options):
        self.approvals.append((conv, title, detail, options))
        return self.answer

    def record(self, *args, **kwargs):
        self.records.append(args)

    async def notify(self, title, body, conv):
        self.notes.append((title, body))


def make_tools(browser, vault, rec):
    return BrowserTools(browser, vault, key="k", approve=rec.approve, record=rec.record, notify=rec.notify,
                        conv_for=lambda k: "c1")


def texts(result: types.CallToolResult) -> str:
    return " ".join(c.text for c in result.content if isinstance(c, types.TextContent))


# credentials


async def test_fill_password_asks_once_then_types(vault):
    acct = vault.add(domain="127.0.0.1", username="tester", password="pw-123-secret")
    browser, rec = FakeBrowser(), Recorder()
    tools = make_tools(browser, vault, rec)
    r1 = await tools.call("c1", "browser_fill_credential", {"account_id": acct["id"], "field": "password"})
    browser.focus = "text"
    r2 = await tools.call("c1", "browser_fill_credential", {"account_id": acct["id"], "field": "username"})
    assert not r1.is_error and not r2.is_error
    assert browser.typed == ["pw-123-secret", "tester"]
    assert len(rec.approvals) == 1 and "Log in to 127.0.0.1 as tester?" in rec.approvals[0][1]
    assert "pw-123-secret" not in texts(r1) + texts(r2)
    assert all("pw-123-secret" not in str(r) for r in rec.records)


async def test_fill_auto_policy_skips_approval(vault):
    acct = vault.add(domain="127.0.0.1", username="tester", password="pw", policy="auto")
    browser, rec = FakeBrowser(), Recorder()
    r = await make_tools(browser, vault, rec).call("c1", "browser_fill_credential",
                                                   {"account_id": acct["id"], "field": "password"})
    assert not r.is_error and rec.approvals == [] and browser.typed == ["pw"]


async def test_fill_denied_types_nothing(vault):
    acct = vault.add(domain="127.0.0.1", username="tester", password="pw")
    browser, rec = FakeBrowser(), Recorder(answer="reject_once")
    r = await make_tools(browser, vault, rec).call("c1", "browser_fill_credential",
                                                   {"account_id": acct["id"], "field": "password"})
    assert r.is_error and browser.typed == []


@pytest.mark.parametrize("url,focus,field,why", [
    ("https://evil.example/login", "password", "password", "Refused"),        # wrong site
    ("http://127.0.0.1:5000/login.html", "text", "password", "not a password field"),
    ("http://127.0.0.1:5000/login.html", None, "password", "No input has focus"),
    ("http://127.0.0.1:5000/login.html", "iframe", "username", "inside a frame"),
])
async def test_fill_refusals(vault, url, focus, field, why):
    acct = vault.add(domain="127.0.0.1", username="tester", password="pw")
    browser, rec = FakeBrowser(url, focus), Recorder()
    r = await make_tools(browser, vault, rec).call("c1", "browser_fill_credential",
                                                   {"account_id": acct["id"], "field": field})
    assert r.is_error and why in texts(r)
    assert browser.typed == [] and rec.approvals == []


async def test_list_accounts_never_shows_passwords(vault):
    vault.add(domain="127.0.0.1", username="tester", password="pw-hidden")
    vault.add(domain="other.org", username="b", password="q-hidden")
    r = await make_tools(FakeBrowser(), vault, Recorder()).call("c1", "browser_list_accounts", {})
    out = texts(r)
    assert "tester" in out and "pw-hidden" not in out and "q-hidden" not in out
    assert '"matches_current_page": true' in out


async def test_totp_requires_a_saved_secret(vault):
    acct = vault.add(domain="127.0.0.1", username="tester", password="pw")
    r = await make_tools(FakeBrowser(focus="text"), vault, Recorder()).call(
        "c1", "browser_fill_totp", {"account_id": acct["id"]})
    assert r.is_error and "no saved 2FA" in texts(r)


# takeover


async def test_calls_wait_while_user_has_control(vault):
    browser = FakeBrowser()
    tools = make_tools(browser, vault, Recorder())
    await browser.take()
    task = asyncio.create_task(tools.call("c1", "browser_list_accounts", {}))
    await asyncio.sleep(0.2)
    assert not task.done()
    await browser.release()
    result = await asyncio.wait_for(task, 2)
    assert texts(result).startswith(WAITED_NOTE)


async def test_request_takeover_blocks_until_release(vault):
    browser, rec = FakeBrowser(), Recorder()
    tools = make_tools(browser, vault, rec)
    task = asyncio.create_task(tools.call("c1", "browser_request_takeover", {"reason": "Solve the CAPTCHA"}))
    await asyncio.sleep(0.2)
    assert browser.controller == "user" and not task.done()
    assert rec.notes == [("Needs you in the browser", "Solve the CAPTCHA")]
    await browser.release()
    assert "gave the browser back" in texts(await asyncio.wait_for(task, 2))


# proxy gate (no upstream needed: denial happens before forwarding)


async def test_risky_click_denied_is_not_forwarded(vault):
    browser, rec = FakeBrowser("http://127.0.0.1:5000/shop.html"), Recorder(answer="reject_once")
    tools = make_tools(browser, vault, rec)
    tools.upstream_tools = [types.Tool(name="browser_click", input_schema={"type": "object"})]
    r = await tools.call("c1", "browser_click", {"element": "Buy now button", "target": "e5"})
    assert r.is_error and "did not allow" in texts(r)
    assert rec.approvals[0][3] == ["allow_once", "allow_site", "reject_once"]
    assert tools.upstream is None  # never contacted


async def test_auto_approved_task_skips_the_ok_except_to_pay(vault):
    browser, rec = FakeBrowser("https://www.linkedin.com/jobs/view/1/"), Recorder(answer="reject_once")
    tools = BrowserTools(browser, vault, key="k", approve=rec.approve, record=rec.record, notify=rec.notify,
                         conv_for=lambda k: "c1", auto_approve=lambda conv: conv == "sweep")
    tools.upstream_tools = [types.Tool(name=n, input_schema={"type": "object"})
                            for n in ("browser_click", "browser_file_upload")]
    forwarded = []

    async def up_call(name, args):
        forwarded.append(name)
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])
    tools.up.call = up_call
    for name, args in [("browser_file_upload", {"paths": ["/lib/resume.pdf"]}),
                       ("browser_click", {"element": "Submit application", "target": "e9"})]:
        assert not (await tools.call("sweep", name, args)).is_error
    assert forwarded == ["browser_file_upload", "browser_click"] and rec.approvals == []
    assert ("approval", 'Click "Submit application" on www.linkedin.com?', "sweep", "auto-approved",
            "https://www.linkedin.com/jobs/view/1/") in rec.records
    assert (await tools.call("sweep", "browser_click", {"element": "Pay now button", "target": "e2"})).is_error
    assert (await tools.call("c1", "browser_click", {"element": "Submit application", "target": "e9"})).is_error
    assert len(rec.approvals) == 2 and forwarded == ["browser_file_upload", "browser_click"]


async def test_saved_screenshot_returns_only_its_path(vault):
    """An evidence screenshot (with filename) is for the user: its image would be re-read on every later step."""
    tools = make_tools(FakeBrowser(), vault, Recorder())
    tools.upstream_tools = [types.Tool(name="browser_take_screenshot", input_schema={"type": "object"})]
    shot = [types.TextContent(type="text", text="### Result\n- [Screenshot](page.png)"),
            types.ImageContent(type="image", data="iVBORw0KGgo=", mimeType="image/png")]

    async def up_call(name, args):
        return types.CallToolResult(content=list(shot))
    tools.up.call = up_call
    saved = await tools.call("c1", "browser_take_screenshot", {"filename": "/lib/Pages/form.png", "fullPage": True})
    assert not any(isinstance(c, types.ImageContent) for c in saved.content)
    assert "Saved to /lib/Pages/form.png" in texts(saved) and "### Result" in texts(saved)
    looked = await tools.call("c1", "browser_take_screenshot", {})                 # no filename: Milo wants to see it
    assert any(isinstance(c, types.ImageContent) for c in looked.content)


async def test_tab_list_shows_only_when_tabs_change(vault):
    """The tab list came with every click: on a long form it was most of each result, re-read on every step."""
    tools = make_tools(FakeBrowser(), vault, Recorder())
    tools.upstream_tools = [types.Tool(name=n, input_schema={"type": "object"}) for n in ("browser_click", "browser_tabs")]
    page = "### Page\n- Page URL: https://a.b/apply\n"
    two = "### Open tabs\n- 0: [Old](https://x.y/)\n- 1: (current) [Apply](https://a.b/apply)\n"
    three = two + "- 2: [Verify](https://a.b/verify)\n"
    reply = {"text": two}

    async def up_call(name, args):
        return types.CallToolResult(content=[types.TextContent(type="text", text="### Ran\n" + reply["text"] + page)])
    tools.up.call = up_call
    first = texts(await tools.call("c1", "browser_click", {"element": "Next"}))
    again = texts(await tools.call("c1", "browser_click", {"element": "Yes"}))
    assert "[Old]" in first and "[Old]" not in again
    assert "2 tabs, unchanged" in again and "Page URL: https://a.b/apply" in again
    reply["text"] = three                                                   # a link opened a tab
    assert "[Verify]" in texts(await tools.call("c1", "browser_click", {"element": "Verify link"}))
    assert "[Old]" in texts(await tools.call("c1", "browser_tabs", {"action": "list"}))   # asked for: always shown


async def test_excluded_tool_is_refused(vault):
    tools = make_tools(FakeBrowser(), vault, Recorder())
    r = await tools.call("c1", "browser_evaluate", {"function": "() => document.cookie"})
    assert r.is_error and "disabled" in texts(r)


def test_scrub_replaces_filled_secrets(vault):
    tools = make_tools(FakeBrowser(), vault, Recorder())
    tools._secrets.add("hunter2")
    res = types.CallToolResult(content=[types.TextContent(type="text", text='textbox "Password": hunter2')])
    assert "hunter2" not in texts(tools._scrub(res))


async def test_tool_list_hides_dangerous_tools(vault):
    tools = make_tools(FakeBrowser(), vault, Recorder())
    tools.upstream_tools = [types.Tool(name="browser_navigate", input_schema={"type": "object"})]
    listed = {t.name for t in (await tools._list_tools(None, None)).tools}
    assert {t.name for t in EXTRA_TOOLS} <= listed and "browser_navigate" in listed
    assert not listed & EXCLUDED


# HTTP endpoint auth


async def test_mcp_endpoint_requires_the_key(vault):
    tools = make_tools(FakeBrowser(), vault, Recorder())
    app = BrowserMCPApp(tools)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json",
               "host": "127.0.0.1:8765"}
    async with tools.manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as c:
            assert (await c.post("/", json=init, headers=headers)).status_code == 401
            bad = await c.post("/", json=init, headers={**headers, "authorization": "Bearer nope"})
            assert bad.status_code == 401
            ok = await c.post("/", json=init, headers={**headers, "authorization": "Bearer k"})
            assert ok.status_code == 200 and "milo-browser" in ok.text


async def test_a_hung_upstream_call_times_out_and_restarts():
    """browser_tabs list waited for ever on a wedged tab until goose's 300 s idle timeout (2026-10-27). A call now
    gives up, restarts the server, and is not retried (a click could run twice)."""
    from mcp_proxy import Upstream, UpstreamTimeout
    up = Upstream("t", "true", [], timeout=lambda name, args: 0.05)
    calls, restarts = [], []

    class Hangs:
        async def call_tool(self, name, args):
            calls.append(name)
            await asyncio.Event().wait()

    async def restart():
        restarts.append(1)
    up.session, up.restart = Hangs(), restart
    with pytest.raises(UpstreamTimeout):
        await asyncio.wait_for(up.call("browser_tabs", {"action": "list"}), 2)
    assert calls == ["browser_tabs"] and restarts == [1]


async def test_a_hung_browser_tool_reopens_the_stuck_tab_and_answers(vault):
    tools = make_tools(FakeBrowser(), vault, Recorder())
    tools.upstream_tools = [types.Tool(name="browser_tabs", input_schema={"type": "object"})]
    tools.call_timeout = 0.05
    reopened = []

    class Hangs:
        async def call_tool(self, name, args):
            await asyncio.Event().wait()

    async def restart():
        pass

    async def reopen_stuck_tabs():
        reopened.append(1)
        return ["vista deadline 2027 - Google Search"]
    tools.up.session, tools.up.restart = Hangs(), restart
    tools.browser.reopen_stuck_tabs = reopen_stuck_tabs
    r = await asyncio.wait_for(tools.call("c1", "browser_tabs", {"action": "list"}), 2)
    assert r.is_error and reopened == [1]
    assert "did not respond" in texts(r) and "vista deadline 2027" in texts(r) and "browser_snapshot" in texts(r)
    assert tools._timeout("browser_wait_for", {"time": 30}) == 30.05   # a wait gets its own time on top
    tools.browser.page.is_closed = lambda: False
    await asyncio.wait_for(tools.select_shown(), 2)                      # the minute loop recovers the same way
    assert reopened == [1, 1]
