"""The milo-browser MCP server. Claude Code (via goose) calls it; it proxies Playwright MCP and adds:

- a pause while the user has control of the browser,
- approval cards for risky actions (buy, send, delete, upload, ...),
- saved-account fills typed by the bridge, so secrets never reach the model,
- an Activity log entry for each browser action.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from mcp import types
from mcp.server.lowlevel import Server

from browser import BrowserManager
from mcp_proxy import BearerEndpoint, Upstream, UpstreamTimeout, session_manager
from vault import Vault

log = logging.getLogger("browser-mcp")

PLAYWRIGHT_MCP = "@playwright/mcp@0.0.83"
# Closing or resizing would break the shared window; arbitrary JS and request bodies could read a filled password.
EXCLUDED = {"browser_close", "browser_resize", "browser_evaluate", "browser_run_code_unsafe",
            "browser_network_request", "browser_network_requests", "browser_install"}
LOGGED = {"browser_navigate", "browser_navigate_back", "browser_click", "browser_type", "browser_select_option",
          "browser_press_key", "browser_fill_form", "browser_tabs", "browser_file_upload", "browser_drop",
          "browser_handle_dialog", "browser_drag"}
RISKY = re.compile(
    r"\b(buy|purchase|pay|payment|place (?:an |the |my )?order|order now|checkout|check out|confirm|submit|send|"
    r"post|publish|delete|remove|subscribe|unsubscribe|book|reserve|transfer|donate|sign up|register|accept|"
    r"cancel (?:my |the )?(?:subscription|account|order|booking|reservation))\b", re.I)
# Clicks that spend money ask even in a task the user set to auto-approve
MONEY = re.compile(r"\b(buy|purchase|pay|payment|place (?:an |the |my )?order|order now|checkout|check out|"
                   r"transfer|donate)\b", re.I)
WAITED_NOTE = ("[The user had control of the browser while this call waited. The page may have changed: "
               "take a fresh snapshot before you act.]")
CRED_APPROVAL_TTL = 600
CALL_TIMEOUT = 90   # s a browser tool may take (plus a wait's own time) before it is given up and the tools restart
TABS = re.compile(r"### Open tabs\n((?:- \d+: .*(?:\n|$))+)")
TAB_ROW = re.compile(r"^- (\d+): (\(current\) )?\[.*\]\((.*)\)$", re.M)

Approve = Callable[[str | None, str, str, list[str]], Awaitable[str | None]]
Record = Callable[..., None]
Notify = Callable[[str, str, str | None], Awaitable[None]]

EXTRA_TOOLS = [
    types.Tool(
        name="browser_list_accounts",
        description="List the user's saved accounts (label, site, username). Passwords are never shown. "
                    "Accounts that match the current page are marked.",
        input_schema={"type": "object", "properties": {}}),
    types.Tool(
        name="browser_fill_credential",
        description="Type a saved username or password into the input that has focus. First click that input with "
                    "browser_click, then call this. The secret never enters your context. It only works when the "
                    "page's site matches the account's site, and a password only goes into a password field. "
                    "Never ask the user for a password in chat; use this tool or browser_request_takeover.",
        input_schema={"type": "object", "required": ["account_id", "field"], "properties": {
            "account_id": {"type": "string", "description": "id from browser_list_accounts"},
            "field": {"type": "string", "enum": ["username", "password"]}}}),
    types.Tool(
        name="browser_fill_totp",
        description="Type the current 2FA code (TOTP) of a saved account into the focused input. Same rules as "
                    "browser_fill_credential.",
        input_schema={"type": "object", "required": ["account_id"], "properties": {
            "account_id": {"type": "string"}}}),
    types.Tool(
        name="browser_request_takeover",
        description="Hand the browser to the user and wait until they give it back. Use it for CAPTCHAs, 2FA codes "
                    "you can't fill, payment details, or any choice the user should make. Say clearly what they "
                    "should do. After it returns, take a fresh snapshot.",
        input_schema={"type": "object", "required": ["reason"], "properties": {
            "reason": {"type": "string", "description": "short instruction shown to the user"}}}),
]


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def risk_of(name: str, args: dict) -> str | None:
    """A short description of why this call needs the user's OK, or None."""
    element = str(args.get("element") or "")
    if name == "browser_click" and RISKY.search(element):
        return f'Click "{element}"'
    if name == "browser_type" and RISKY.search(element):
        return f'Type into "{element}"' + (" and submit" if args.get("submit") else "")
    if name == "browser_select_option" and RISKY.search(element):
        return f'Choose an option in "{element}"'
    if name == "browser_file_upload" and args.get("paths"):
        files = ", ".join(str(p).rsplit("/", 1)[-1] for p in args["paths"])
        return f"Upload {len(args['paths'])} file(s): {files}"
    if name == "browser_drop" and args.get("paths"):
        return f"Drop {len(args['paths'])} file(s) onto the page"
    return None


def describe(name: str, args: dict) -> str:
    element = args.get("element") or ""
    return {
        "browser_navigate": f"Open {args.get('url', '')}",
        "browser_navigate_back": "Go back",
        "browser_click": f"Click {element}",
        "browser_type": f"Type into {element}",
        "browser_select_option": f"Choose in {element}",
        "browser_press_key": f"Press {args.get('key', '')}",
        "browser_fill_form": f"Fill {len(args.get('fields') or [])} form field(s)",
        "browser_tabs": f"Tabs: {args.get('action', '')}",
        "browser_file_upload": "Upload files",
        "browser_drop": "Drop files",
        "browser_handle_dialog": "Accept dialog" if args.get("accept") else "Dismiss dialog",
        "browser_drag": "Drag",
    }.get(name, name.removeprefix("browser_").replace("_", " ").capitalize())


def pretty_title(title: str) -> str:
    """'mcp: milo-browser  browser_navigate' -> 'Browser: navigate'."""
    m = re.match(r"mcp:\s*milo-browser\s+(?:browser_)?(\w+)", title or "")
    return f"Browser: {m.group(1).replace('_', ' ')}" if m else title


OLD_OUTPUT = Path(__file__).parent / ".playwright-mcp"   # the output folder before #85: old replies show pictures there


def text_result(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def saved_only(result: types.CallToolResult, filename: str) -> types.CallToolResult:
    """A screenshot saved to a file is evidence for the user. Its image would stay in the chat's context and be
    re-read on every later step, so Claude gets only the path."""
    if result.is_error:
        return result
    content = [c for c in result.content if not isinstance(c, types.ImageContent)]
    if len(content) == len(result.content):
        return result
    content.append(types.TextContent(type="text", text=f"[Saved to {filename}. The image is not shown, to save "
                                                       "tokens. To check the page, use browser_snapshot.]"))
    return result.model_copy(update={"content": content})


class BrowserTools:
    def __init__(self, browser: BrowserManager, vault: Vault, *, key: str, approve: Approve, record: Record,
                 notify: Notify, conv_for: Callable[[str | None], str | None], files_dir: str | None = None,
                 output_dir: str | None = None, auto_approve: Callable[[str | None], bool] = lambda conv: False):
        self.browser = browser
        self.vault = vault
        self.key = key
        self.approve = approve
        self.record = record
        self.notify = notify
        self.conv_for = conv_for
        self.auto_approve = auto_approve   # conv -> the user lets this task's risky actions run without asking
        # Playwright MCP reads and writes files (uploads, screenshots) only under its working folder and its
        # output folder. Run it in the Library, so it can upload Milo's files but not the code folder's data/.
        # The output folder is Temp, which /api/picture serves: a screenshot for the user shows in the chat (#85).
        args = ["-y", PLAYWRIGHT_MCP, "--cdp-endpoint", browser.cdp_url]
        if files_dir:   # snapshots and console logs stay out of the Library
            args += ["--output-dir", str(output_dir or OLD_OUTPUT)]
        self.up = Upstream("playwright mcp", "npx", args, exclude=EXCLUDED, annotate=self._annotate, cwd=files_dir,
                           timeout=self._timeout)
        self.call_timeout = CALL_TIMEOUT
        self._secrets: set[str] = set()          # filled secrets, scrubbed from every tool result
        self._site_ok: set[tuple[str | None, str]] = set()   # (conv, host) the user allowed for the task
        self._cred_ok: dict[tuple[str | None, str], float] = {}
        self._tabs: dict[str | None, tuple[int, int]] = {}   # conv -> (tab count, current tab) last shown
        self.server = Server("milo-browser", version="1.0",
                             instructions="Milo's browser on the user's Mac. Prefer browser_snapshot to see the page.",
                             on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.manager = session_manager(self.server)

    # upstream Playwright MCP (see mcp_proxy.Upstream)

    @property
    def upstream(self):
        return self.up.session

    @property
    def upstream_tools(self) -> list[types.Tool]:
        return self.up.tools

    @upstream_tools.setter
    def upstream_tools(self, tools: list[types.Tool]) -> None:
        self.up.tools = tools

    async def start_upstream(self) -> None:
        await self.up.start()

    async def restart_upstream(self) -> None:
        await self.up.restart()

    async def stop_upstream(self) -> None:
        await self.up.stop()

    def _timeout(self, name: str, args: dict) -> float:
        try:
            waits = float(args.get("time") or 0) if name == "browser_wait_for" else 0
        except (TypeError, ValueError):
            waits = 0
        return self.call_timeout + waits

    @staticmethod
    def _annotate(tool: types.Tool) -> types.Tool:
        if tool.name == "browser_type":
            note = " Never use this for passwords: use browser_fill_credential."
            return tool.model_copy(update={"description": (tool.description or "") + note})
        return tool

    async def select_shown(self) -> None:
        """When its tab closes, Playwright MCP goes on in a neighbour, which can be a tab the user opened: after
        BrowserManager.close_milos_tabs, go on in the tab on show."""
        page = self.browser.page
        if self.up.session is None or not page or page.is_closed():
            return
        try:
            tabs = await self.up.call("browser_tabs", {"action": "list"})
        except UpstreamTimeout:   # a wedged tab: reopen it now, not when the next chat's first tool hangs
            await self.browser.reopen_stuck_tabs()
            return
        listed = "\n".join(c.text for c in tabs.content if isinstance(c, types.TextContent))
        rows = TAB_ROW.findall(listed)
        if any(current and url == page.url for _, current, url in rows):
            return
        same = [int(i) for i, _, url in rows if url == page.url]
        if len(same) == 1:
            await self.up.call("browser_tabs", {"action": "select", "index": same[0]})

    def forget_task(self, conv: str | None) -> None:
        self._site_ok = {s for s in self._site_ok if s[0] != conv}
        self._cred_ok = {k: v for k, v in self._cred_ok.items() if k[0] != conv}

    # MCP handlers

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=self.upstream_tools + EXTRA_TOOLS)

    async def _call_tool(self, ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        key = ctx.request.query_params.get("k") if ctx.request is not None else None
        return await self.call(self.conv_for(key), params.name, dict(params.arguments or {}))

    async def call(self, conv: str | None, name: str, args: dict) -> types.CallToolResult:
        try:
            await self.browser.ensure_running()
        except Exception as e:
            return text_result(f"The browser is not available: {e}", error=True)
        if name == "browser_request_takeover":
            return await self._takeover(conv, str(args.get("reason") or "Please take over the browser."))
        waited = await self.browser.wait_for_milo_turn()
        if conv:
            await self.browser.acquire(conv)
        try:
            if name == "browser_list_accounts":
                result = self._list_accounts()
            elif name in ("browser_fill_credential", "browser_fill_totp"):
                result = await self._fill(conv, name, args)
            else:
                result = await self._proxy(conv, name, args)
        except Exception as e:
            log.exception("browser tool %s failed", name)
            result = text_result(f"{name} failed: {e}", error=True)
        if waited:
            result.content.insert(0, types.TextContent(type="text", text=WAITED_NOTE))
        return result

    async def _proxy(self, conv: str | None, name: str, args: dict) -> types.CallToolResult:
        if name in EXCLUDED or not any(t.name == name for t in self.upstream_tools):
            return text_result(f"Unknown or disabled tool: {name}", error=True)
        url = self.browser.page.url if self.browser.page else ""
        reason = risk_of(name, args)
        spends = name == "browser_click" and MONEY.search(str(args.get("element") or ""))
        if reason and (conv, host_of(url)) not in self._site_ok and self.auto_approve(conv) and not spends:
            self.record("approval", f"{reason} on {host_of(url) or 'this page'}?", conv, "auto-approved", url)
        elif reason and (conv, host_of(url)) not in self._site_ok:
            choice = await self.approve(conv, f"{reason} on {host_of(url) or 'this page'}?",
                                        f"{url}\n{json.dumps(args, indent=1)[:600]}",
                                        ["allow_once", "allow_site", "reject_once"])
            if choice == "allow_site":
                self._site_ok.add((conv, host_of(url)))
            elif choice != "allow_once":
                self.record("browser", f"Blocked: {reason}", conv, "denied", url)
                return text_result("The user did not allow this action. Do not try it another way; "
                                   "tell the user what you were about to do.", error=True)
        try:
            result = await self.up.call(name, args)
        except UpstreamTimeout as e:
            return await self._stuck(conv, name, args, e)
        result = self._trim_tabs(conv, name, self._scrub(result))
        if name == "browser_take_screenshot" and args.get("filename"):
            result = saved_only(result, str(args["filename"]))
        if name in LOGGED:
            after = self.browser.page.url if self.browser.page else url
            self.record("browser", describe(name, args), conv, "failed" if result.is_error else "done", after)
        return result

    async def _stuck(self, conv: str | None, name: str, args: dict, e: UpstreamTimeout) -> types.CallToolResult:
        """Upstream gave up on the call and restarted Playwright MCP. A tab that never answers would hang the new
        one too (it lists every tab after each action), so reopen such tabs before the model tries again."""
        try:
            reopened = await self.browser.reopen_stuck_tabs()
        except Exception:
            log.exception("couldn't check the tabs after %s hung", name)
            reopened = []
        self._tabs.pop(conv, None)
        if name in LOGGED:
            url = self.browser.page.url if self.browser.page else ""
            self.record("browser", describe(name, args), conv, "failed", url)
        note = f" A tab that did not respond was reopened: {', '.join(reopened)}." if reopened else ""
        return text_result(f"The browser did not respond ({e}).{note} The browser tools were restarted. "
                           "The action may or may not have happened: call browser_snapshot to see the page, "
                           "then try again.", error=True)

    def _scrub(self, result: types.CallToolResult) -> types.CallToolResult:
        if not self._secrets:
            return result
        content = []
        for item in result.content:
            if isinstance(item, types.TextContent):
                text = item.text
                for s in self._secrets:
                    text = text.replace(s, "[saved secret]")
                item = item.model_copy(update={"text": text})
            content.append(item)
        return result.model_copy(update={"content": content})

    def _trim_tabs(self, conv: str | None, name: str, result: types.CallToolResult) -> types.CallToolResult:
        """Playwright MCP lists every open tab after each action. On a long form that list was most of each result,
        and every later step re-reads it, so it is shown only when the tabs change."""
        content = []
        for item in result.content:
            if isinstance(item, types.TextContent) and (m := TABS.search(item.text)):
                rows = m.group(1).strip().splitlines()
                now = (len(rows), next((i for i, r in enumerate(rows) if "(current)" in r), -1))
                if name != "browser_tabs" and self._tabs.get(conv) == now:
                    note = f"### Open tabs\n{now[0]} tabs, unchanged (browser_tabs lists them)\n"
                    item = item.model_copy(update={"text": item.text[:m.start()] + note + item.text[m.end():]})
                self._tabs[conv] = now
            content.append(item)
        return result.model_copy(update={"content": content})

    # extra tools

    def _list_accounts(self) -> types.CallToolResult:
        url = self.browser.page.url if self.browser.page else ""
        here = {a["id"] for a in self.vault.for_url(url)}
        rows = [{"id": a["id"], "label": a["label"], "site": a["domain"], "username": a["username"],
                 "matches_current_page": a["id"] in here, "has_2fa": a["has_totp"]} for a in self.vault.accounts()]
        if not rows:
            return text_result("No saved accounts. If a login is needed, call browser_request_takeover so the user "
                               "can log in, or ask them to add the account in Milo's Settings > Accounts.")
        return text_result(json.dumps(rows, indent=1))

    async def _fill(self, conv: str | None, name: str, args: dict) -> types.CallToolResult:
        aid = str(args.get("account_id") or "")
        field = "totp" if name == "browser_fill_totp" else str(args.get("field") or "")
        acct = self.vault.get(aid)
        if not acct:
            return text_result("Unknown account_id. Call browser_list_accounts first.", error=True)
        if field not in ("username", "password", "totp"):
            return text_result("field must be 'username' or 'password'.", error=True)
        if field == "totp" and not acct["has_totp"]:
            return text_result("This account has no saved 2FA secret. Call browser_request_takeover.", error=True)
        focused = await self.browser.focused_input()
        if not focused:
            return text_result(f"No input has focus. Click the {field} field first.", error=True)
        page, kind = focused
        if kind == "iframe":
            return text_result("The login form is inside a frame. Call browser_request_takeover.", error=True)
        if field == "password" and kind != "password":
            return text_result("The focused input is not a password field. Click the password field first.",
                               error=True)
        if not self.vault.matches(aid, page.url):
            self.record("browser", f"Refused to fill {acct['domain']} account on {host_of(page.url)}", conv,
                        "refused", page.url)
            return text_result(f"Refused: this account is for {acct['domain']}, but the page is "
                               f"{host_of(page.url) or page.url}.", error=True)
        if acct["policy"] == "ask" and time.time() - self._cred_ok.get((conv, aid), 0) > CRED_APPROVAL_TTL:
            choice = await self.approve(conv, f"Log in to {acct['domain']} as {acct['username']}?",
                                        f"Milo wants to type your saved {field} on {host_of(page.url)}.",
                                        ["allow_once", "reject_once"])
            if choice != "allow_once":
                self.record("browser", f"Login to {acct['domain']} not allowed", conv, "denied", page.url)
                return text_result("The user did not allow this login.", error=True)
            self._cred_ok[(conv, aid)] = time.time()
        value = self.vault.secret(aid, field)
        if not value:
            return text_result("The secret is missing from the Keychain. Ask the user to re-add the account.",
                               error=True)
        if field != "username":
            self._secrets.add(value)
        await self.browser.type_secret(page, value)
        self.vault.touch(aid)
        label = {"username": "username", "password": "password", "totp": "2FA code"}[field]
        self.record("browser", f"Filled {label} for {acct['domain']}", conv, "done", page.url)
        return text_result(f"Typed the saved {label} for {acct['label']} into the focused field.")

    async def _takeover(self, conv: str | None, reason: str) -> types.CallToolResult:
        await self.browser.take(reason)
        self.record("browser", f"Asked you to take over: {reason}", conv, "waiting", self.browser.state()["url"])
        await self.notify("Needs you in the browser", reason, conv)   # iOS adds "from Milo"
        await self.browser.wait_for_milo_turn()
        self.record("browser", "You gave the browser back", conv, "done", self.browser.state()["url"])
        return text_result("The user finished and gave the browser back. Take a fresh snapshot before you continue.")


def BrowserMCPApp(tools: "BrowserTools") -> BearerEndpoint:
    """ASGI endpoint for /mcp/browser with a bearer-key check in front of the MCP transport."""
    return BearerEndpoint(tools.manager, tools.key)
