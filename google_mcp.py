"""The milo-google MCP server: Gmail, Calendar and Drive for several Google accounts.

It proxies the open-source workspace-mcp server (every tool takes user_google_email) and adds:
- a list of the accounts the user connected, with labels such as "work" or "personal",
- a check that each call names one of those accounts,
- a sign-in flow that opens Google's consent page in Milo's own browser (never the user's main browser).
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, unquote

import httpx
from mcp import types
from mcp.server.lowlevel import Server

from features import JsonFile
from mcp_proxy import BearerEndpoint, Upstream, session_manager

log = logging.getLogger("google-mcp")

WORKSPACE_MCP = "workspace-mcp==2.1.0"
CALLBACK_PORT = 8766
AUTH_URL = re.compile(r"(https://accounts\.google\.com/o/oauth2/\S+)")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NEEDS_AUTH = "ACTION REQUIRED: Google Authentication"
TOKEN_OK_FOR = 600        # a token that refreshed is checked again after 10 min
TOKEN_UNKNOWN_FOR = 60    # Google did not answer: try again in a minute
DEAD_TOKEN = {"invalid_grant", "invalid_client", "unauthorized_client"}

LIST_TOOL = types.Tool(
    name="google_list_accounts",
    description="List the Google accounts the user connected to Milo (email and label, e.g. 'work'). Pass one of these "
                "emails as user_google_email to every Gmail, Calendar and Drive tool of this server.",
    input_schema={"type": "object", "properties": {}})

Record = Callable[..., None]


def text_result(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


async def refresh_works(creds: dict) -> bool | None:
    """Ask Google for a new access token with the saved refresh token. False: Google expired or revoked it
    (7 days for a client in testing), so the account must sign in again. None: unknown (no answer)."""
    if not creds.get("refresh_token") or not creds.get("token_uri"):
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(creds["token_uri"], data={
                "grant_type": "refresh_token", "refresh_token": creds["refresh_token"],
                "client_id": creds.get("client_id", ""), "client_secret": creds.get("client_secret", "")})
    except httpx.HTTPError:
        return None
    if r.status_code == 200:
        return True
    try:
        error = r.json().get("error")
    except ValueError:
        error = None
    return False if error in DEAD_TOKEN else None


class GoogleTools:
    def __init__(self, data_dir: Path, *, key: str, client: Callable[[], tuple[str, str] | None], record: Record):
        self.key = key
        self.client = client          # () -> (client_id, client_secret) or None when not set up
        self.record = record
        # (chat key from the MCP URL, tool, args) -> why the call is refused, or None; the bridge sets it
        self.guard: Callable[[str | None, str, dict], str | None] | None = None
        self.accounts = JsonFile(data_dir / "google_accounts.json", [])
        self.creds_dir = data_dir / "google-credentials"
        self.creds_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.creds_dir, 0o700)
        self.up = Upstream("workspace mcp", "uvx", [WORKSPACE_MCP, "--tools", "gmail", "calendar", "drive",
                                                    "--tool-tier", "extended"], env=self._env)
        # workspace-mcp binds its session to the first account that uses it and refuses the others,
        # so each switch to another account starts a new session (one call at a time)
        self.bound: str | None = None
        self.lock = asyncio.Lock()
        # a saved token can be dead (expired or revoked) while its file is still there:
        # email -> (file mtime, when checked, refresh worked), so Settings can offer Sign in
        self.checked: dict[str, tuple[float, float, bool | None]] = {}
        self.refresh = refresh_works
        self.server = Server("milo-google", version="1.0",
                             instructions="Gmail, Calendar and Drive for the user's Google accounts. "
                                          "Call google_list_accounts first.",
                             on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.manager = session_manager(self.server)

    # setup

    @property
    def configured(self) -> bool:
        return self.client() is not None

    def _env(self) -> dict:
        client_id, secret = self.client() or ("", "")
        return {**os.environ,
                "GOOGLE_OAUTH_CLIENT_ID": client_id, "GOOGLE_OAUTH_CLIENT_SECRET": secret,
                "WORKSPACE_MCP_PORT": str(CALLBACK_PORT), "WORKSPACE_MCP_HOST": "127.0.0.1",
                "GOOGLE_OAUTH_REDIRECT_URI": f"http://localhost:{CALLBACK_PORT}/oauth2callback",
                "WORKSPACE_MCP_CREDENTIALS_DIR": str(self.creds_dir),
                "OAUTHLIB_INSECURE_TRANSPORT": "1",      # the callback is plain http on localhost
                "BROWSER": "true"}                       # never pop the consent page in the user's main browser

    async def start(self) -> None:
        if self.configured:
            await self.up.start()

    async def restart(self) -> None:
        await self.up.stop()
        self.bound = None
        await self.start()

    async def _call_as(self, email: str, name: str, args: dict) -> types.CallToolResult:
        """Call workspace-mcp in a session that belongs to this account."""
        async with self.lock:
            if self.bound and self.bound != email:
                log.info("workspace mcp: new session for %s", email)
                await self.up.restart()
            self.bound = email
            return await self.up.call(name, {**args, "user_google_email": email})

    # accounts

    def creds_file(self, email: str) -> Path | None:
        email = email.lower()
        return next((f for f in self.creds_dir.glob("*.json") if unquote(f.stem).lower() == email), None)

    def creds_mtime(self, email: str) -> float | None:
        f = self.creds_file(email)
        return f.stat().st_mtime if f else None

    def connected(self, email: str) -> bool:
        """A token is saved (it may still be dead: see expired)."""
        return self.creds_file(email) is not None

    def expired(self, email: str) -> bool:
        """The saved token was found dead and no new one came since."""
        email = email.lower()
        seen = self.checked.get(email)
        return bool(seen and seen[2] is False and seen[0] == self.creds_mtime(email))

    def mark_expired(self, email: str) -> None:
        if (mtime := self.creds_mtime(email)) is not None:
            self.checked[email.lower()] = (mtime, time.time(), False)

    async def check_tokens(self) -> None:
        """Refresh each saved token whose last check is stale, all at once. A new token file is checked again."""
        now, todo = time.time(), []
        for a in self.accounts.data:
            f = self.creds_file(a["email"])
            if not f:
                continue
            mtime, seen = f.stat().st_mtime, self.checked.get(a["email"])
            if seen and seen[0] == mtime and (seen[2] is False or now - seen[1] <
                                              (TOKEN_OK_FOR if seen[2] else TOKEN_UNKNOWN_FOR)):
                continue
            try:
                creds = json.loads(f.read_text())
            except (OSError, ValueError):
                creds = {}
            todo.append((a["email"], mtime, creds))
        results = await asyncio.gather(*(self.refresh(c) for _, _, c in todo), return_exceptions=True)
        for (email, mtime, _), ok in zip(todo, results):
            self.checked[email] = (mtime, time.time(), None if isinstance(ok, BaseException) else ok)

    def status(self, email: str) -> str:
        return "expired" if self.expired(email) else "connected" if self.connected(email) else "signed_out"

    def list_accounts(self) -> list[dict]:
        rows = []
        for a in self.accounts.data:
            status = self.status(a["email"])
            rows.append({**a, "connected": status == "connected", "status": status})
        return rows

    def find(self, email: str) -> dict | None:
        return next((a for a in self.accounts.data if a["email"] == email.lower().strip()), None)

    def add(self, email: str, label: str = "") -> dict:
        email = email.lower().strip()
        if not EMAIL.match(email):
            raise ValueError("enter a valid email address")
        acct = self.find(email)
        if acct:
            acct["label"] = label.strip() or acct["label"]
        else:
            acct = {"email": email, "label": label.strip() or email.split("@")[0], "added": time.time()}
            self.accounts.data.append(acct)
        self.accounts.save()
        return {**acct, "connected": self.connected(email)}

    def remove(self, email: str) -> bool:
        acct = self.find(email)
        if not acct:
            return False
        self.accounts.data = [a for a in self.accounts.data if a is not acct]
        self.accounts.save()
        for f in self.creds_dir.glob("*.json"):
            if unquote(f.stem).lower() == acct["email"]:
                f.unlink()
        return True

    async def sign_in_url(self, email: str) -> str | None:
        """Start Google sign-in for an account. Returns the consent URL, or None if it is already connected."""
        if not self.configured:
            raise RuntimeError("Set up the Google API client first.")
        result = await self._call_as(email.lower().strip(), "list_calendars", {})
        text = " ".join(c.text for c in result.content if isinstance(c, types.TextContent))
        m = AUTH_URL.search(text)
        if m:
            if self.connected(email):
                self.mark_expired(email)
            url = m.group(1)
            # Google picks this account, so the new token replaces the dead one
            return url if "login_hint=" in url else f"{url}&login_hint={quote(email.lower().strip(), safe='')}"
        if result.is_error:
            raise RuntimeError(text[:300])
        self.checked.pop(email.lower().strip(), None)   # the token works after all
        return None

    def context(self) -> str:
        rows = [f"{a['label']} = {a['email']}" for a in self.accounts.data if self.connected(a["email"])]
        if not rows:
            return ""
        # Milo once called a bare "google_list_accounts" (no such tool), then answered from busy.json (BEHAVIOR #90)
        return ("Google accounts (milo-google tools, named mcp__milo-google__<tool>, such as "
                "mcp__milo-google__get_events; pass the email as user_google_email): " + "; ".join(rows) +
                ". The claude.ai Gmail and Calendar connectors only see the user's main account; use milo-google "
                "for the others or when the user names an account.")

    # MCP handlers

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[LIST_TOOL] + self.up.tools)

    async def _call_tool(self, ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        args = dict(params.arguments or {})
        key = ctx.request.query_params.get("k") if ctx.request is not None else None
        if self.guard and (refused := self.guard(key, params.name, args)):
            return text_result(refused, True)
        return await self.call(params.name, args)

    async def call(self, name: str, args: dict) -> types.CallToolResult:
        if name == "google_list_accounts":
            rows = [{"email": a["email"], "label": a["label"], "connected": a["connected"],
                     **({"needs_sign_in": True} if a["status"] == "expired" else {})} for a in self.list_accounts()]
            return text_result(json.dumps(rows, indent=1) if rows else
                               "No Google accounts connected. Ask the user to add one in Milo's Settings > Google accounts.")
        if not self.configured:
            return text_result("Google accounts are not set up. Ask the user to open Settings > Google accounts.", True)
        connected = [a["email"] for a in self.list_accounts() if a["connected"]]
        email = str(args.get("user_google_email") or "").lower().strip()
        if not email:
            if len(connected) != 1:
                return text_result("Pass user_google_email. Connected accounts: " + (", ".join(connected) or "none"), True)
            email = connected[0]
        if not self.find(email):
            return text_result(f"{email} is not one of the user's connected accounts ({', '.join(connected) or 'none'}).",
                               True)
        if email not in connected:
            return text_result(f"{email} needs to sign in again. Ask the user to tap Sign in next to it in "
                               "Settings > Google accounts.", True)
        result = await self._call_as(email, name, args)
        text = " ".join(c.text for c in result.content if isinstance(c, types.TextContent))
        if NEEDS_AUTH in text:
            self.mark_expired(email)
            return text_result(f"Google needs {email} to sign in again. Ask the user to tap Sign in next to it in "
                               "Settings > Google accounts.", True)
        return result


def GoogleMCPApp(tools: GoogleTools) -> BearerEndpoint:
    return BearerEndpoint(tools.manager, tools.key)
