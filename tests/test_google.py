"""milo-google: account bookkeeping and call routing, with a fake workspace-mcp upstream."""

import json
import os
import time
from urllib.parse import quote

import pytest
from mcp import types

from google_mcp import NEEDS_AUTH, GoogleTools


class FakeUpstream:
    def __init__(self, reply="ok", error=False):
        self.calls = []
        self.reply, self.error = reply, error
        self.tools = [types.Tool(name="search_gmail_messages", input_schema={"type": "object"})]

    async def call(self, name, args):
        self.calls.append((name, args))
        return types.CallToolResult(content=[types.TextContent(type="text", text=self.reply)], is_error=self.error)

    async def start(self):
        pass

    async def restart(self):
        self.calls.append(("restart", {}))

    async def stop(self):
        pass


@pytest.fixture
def g(tmp_path):
    tools = GoogleTools(tmp_path, key="k", client=lambda: ("id.apps.googleusercontent.com", "secret"),
                        record=lambda *a, **k: None)
    tools.up = FakeUpstream()
    return tools


def sign_in(g, email):
    """What workspace-mcp writes after a successful Google sign-in."""
    (g.creds_dir / f"{quote(email, safe='')}.json").write_text("{}")


def text(r):
    return " ".join(c.text for c in r.content if isinstance(c, types.TextContent))


def test_add_validates_and_labels(g):
    acct = g.add("Work.Me@Example.com", "work")
    assert acct == {**acct, "email": "work.me@example.com", "label": "work", "connected": False}
    assert g.add("home@gmail.com")["label"] == "home"
    assert g.add("work.me@example.com", "office")["label"] == "office"     # re-adding updates the label
    assert len(g.list_accounts()) == 2
    with pytest.raises(ValueError):
        g.add("not-an-email")


def test_connected_follows_credential_files(g):
    g.add("a.b+tag@gmail.com")
    assert not g.connected("a.b+tag@gmail.com")
    sign_in(g, "a.b+tag@gmail.com")
    assert g.connected("A.B+tag@gmail.com")
    assert g.remove("a.b+tag@gmail.com") and not list(g.creds_dir.glob("*.json"))
    assert g.remove("a.b+tag@gmail.com") is False


async def test_call_routes_to_the_named_account(g):
    for e in ("work@x.com", "home@y.com"):
        g.add(e)
        sign_in(g, e)
    r = await g.call("search_gmail_messages", {"query": "is:unread", "user_google_email": "HOME@y.com"})
    assert not r.is_error and g.up.calls == [("search_gmail_messages", {"query": "is:unread", "user_google_email": "home@y.com"})]


async def test_each_account_gets_its_own_session(g):
    """workspace-mcp binds a session to one account, so a switch to another account restarts it."""
    for e in ("work@x.com", "home@y.com"):
        g.add(e)
        sign_in(g, e)
    for e in ("work@x.com", "work@x.com", "home@y.com", "work@x.com"):
        await g.call("search_gmail_messages", {"user_google_email": e})
    assert [c[0] for c in g.up.calls] == ["search_gmail_messages", "search_gmail_messages", "restart",
                                          "search_gmail_messages", "restart", "search_gmail_messages"]


async def test_email_required_when_several_accounts(g):
    for e in ("work@x.com", "home@y.com"):
        g.add(e)
        sign_in(g, e)
    r = await g.call("search_gmail_messages", {"query": "x"})
    assert r.is_error and "work@x.com" in text(r) and g.up.calls == []


async def test_single_account_is_the_default(g):
    g.add("only@x.com")
    sign_in(g, "only@x.com")
    await g.call("search_gmail_messages", {"query": "x"})
    assert g.up.calls[0][1]["user_google_email"] == "only@x.com"


async def test_unknown_or_signed_out_accounts_are_refused(g):
    g.add("work@x.com")
    r1 = await g.call("search_gmail_messages", {"user_google_email": "stranger@evil.com"})
    r2 = await g.call("search_gmail_messages", {"user_google_email": "work@x.com"})
    assert r1.is_error and "not one of" in text(r1)
    assert r2.is_error and "sign in again" in text(r2)
    assert g.up.calls == []


async def test_expired_sign_in_is_explained(g):
    g.add("work@x.com")
    sign_in(g, "work@x.com")
    g.up = FakeUpstream(reply=f"**{NEEDS_AUTH} for Gmail** ... Authorization URL: https://accounts.google.com/o/oauth2/auth?x=1",
                        error=True)
    r = await g.call("search_gmail_messages", {"user_google_email": "work@x.com"})
    assert r.is_error and "Settings > Google accounts" in text(r) and "accounts.google.com" not in text(r)


async def test_sign_in_url_is_extracted(g):
    g.up = FakeUpstream(reply="Authorization URL: https://accounts.google.com/o/oauth2/auth?client_id=abc&state=1\n2. After",
                        error=True)
    assert await g.sign_in_url("new@x.com") == "https://accounts.google.com/o/oauth2/auth?client_id=abc&state=1&login_hint=new%40x.com"
    g.up = FakeUpstream(reply='{"calendars": []}')
    assert await g.sign_in_url("new@x.com") is None          # already signed in


async def test_list_accounts_tool_and_context(g):
    g.add("work@x.com", "work")
    g.add("home@y.com", "personal")
    sign_in(g, "work@x.com")
    out = text(await g.call("google_list_accounts", {}))
    assert '"label": "work"' in out and '"connected": false' in out
    ctx = g.context()
    assert "work = work@x.com" in ctx and "home@y.com" not in ctx   # only signed-in accounts are offered


async def test_not_configured(tmp_path):
    g = GoogleTools(tmp_path, key="k", client=lambda: None, record=lambda *a, **k: None)
    assert not g.configured
    r = await g.call("search_gmail_messages", {"user_google_email": "a@b.co"})
    assert r.is_error and "not set up" in text(r)
    with pytest.raises(RuntimeError):
        await g.sign_in_url("a@b.co")


def test_env_never_opens_the_main_browser(g):
    env = g._env()
    assert env["BROWSER"] == "true" and env["WORKSPACE_MCP_HOST"] == "127.0.0.1"
    assert env["WORKSPACE_MCP_CREDENTIALS_DIR"] == str(g.creds_dir)
    assert oct(g.creds_dir.stat().st_mode)[-3:] == "700"


@pytest.mark.e2e
async def test_real_workspace_mcp_starts_and_offers_sign_in(tmp_path):
    """The real upstream with a dummy client: tools load and sign-in yields a consent URL (and opens no browser)."""
    g = GoogleTools(tmp_path, key="k", client=lambda: ("dummy.apps.googleusercontent.com", "dummy"),
                    record=lambda *a, **k: None)
    try:
        await g.start()
        names = {t.name for t in g.up.tools}
        assert {"search_gmail_messages", "send_gmail_message", "get_events", "search_drive_files"} <= names
        url = await g.sign_in_url("someone@example.com")
        assert url.startswith("https://accounts.google.com/o/oauth2/auth")
        assert "client_id=dummy.apps.googleusercontent.com" in url and "localhost%3A8766" in url
    finally:
        await g.up.stop()


def save_token(g, email, refresh="r1"):
    """A token file as workspace-mcp saves it, with a refresh token."""
    f = g.creds_dir / f"{quote(email, safe='')}.json"
    f.write_text(json.dumps({"token": "t", "refresh_token": refresh, "token_uri": "https://oauth2.googleapis.com/token",
                             "client_id": "id", "client_secret": "s"}))
    return f


def fake_refresh(g, works):
    """works: refresh token -> True (Google refreshes it), False (expired or revoked) or None (no answer)."""
    seen = []

    async def refresh(creds):
        seen.append(creds["refresh_token"])
        return works[creds["refresh_token"]]
    g.refresh = refresh
    return seen


async def test_dead_token_shows_sign_in_needed(g):
    """Google expired or revoked a saved token: the file is still there, but the account must sign in again."""
    g.add("work@x.com", "work")
    g.add("home@y.com", "home")
    g.add("new@z.com", "new")
    save_token(g, "work@x.com", "good")
    save_token(g, "home@y.com", "dead")
    fake_refresh(g, {"good": True, "dead": False})
    await g.check_tokens()
    st = {a["email"]: (a["status"], a["connected"]) for a in g.list_accounts()}
    assert st == {"work@x.com": ("connected", True), "home@y.com": ("expired", False), "new@z.com": ("signed_out", False)}
    r = await g.call("search_gmail_messages", {"user_google_email": "home@y.com"})
    assert r.is_error and "sign in again" in text(r) and g.up.calls == []     # refused before workspace-mcp
    assert '"needs_sign_in": true' in text(await g.call("google_list_accounts", {}))


async def test_token_checks_are_cached_and_a_new_token_is_checked_again(g):
    g.add("work@x.com")
    g.add("home@y.com")
    save_token(g, "work@x.com", "good")
    f = save_token(g, "home@y.com", "dead")
    seen = fake_refresh(g, {"good": True, "dead": False, "fresh": True})
    await g.check_tokens()
    await g.check_tokens()
    assert sorted(seen) == ["dead", "good"]                  # the second list is served from the cache
    save_token(g, "home@y.com", "fresh")                     # the user signed in again
    os.utime(f, (time.time() + 5, time.time() + 5))
    await g.check_tokens()
    assert seen[2:] == ["fresh"] and g.status("home@y.com") == "connected"


async def test_unknown_refresh_result_is_not_a_false_alarm(g):
    g.add("work@x.com")
    save_token(g, "work@x.com", "offline")
    fake_refresh(g, {"offline": None})
    await g.check_tokens()
    assert g.status("work@x.com") == "connected"


async def test_failed_call_marks_the_account_and_sign_in_url_has_login_hint(g):
    g.add("work@x.com")
    save_token(g, "work@x.com")
    g.up = FakeUpstream(reply=f"**{NEEDS_AUTH}** Authorization URL: https://accounts.google.com/o/oauth2/auth?x=1", error=True)
    await g.call("search_gmail_messages", {"user_google_email": "work@x.com"})
    assert g.status("work@x.com") == "expired"
    url = await g.sign_in_url("work@x.com")
    assert url.endswith("&login_hint=work%40x.com")
    g.up = FakeUpstream(reply="Authorization URL: https://accounts.google.com/o/oauth2/auth?login_hint=a%40b.c&x=1", error=True)
    assert (await g.sign_in_url("work@x.com")).count("login_hint") == 1


async def test_refresh_works_reads_googles_answer(monkeypatch):
    import httpx
    from google_mcp import refresh_works
    answers = iter([httpx.Response(200, json={"access_token": "a"}),
                    httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."}),
                    httpx.Response(500, text="oops")])
    monkeypatch.setattr(httpx.AsyncClient, "post", lambda self, url, data: _resolved(next(answers)))
    creds = {"refresh_token": "r", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "i", "client_secret": "s"}
    assert await refresh_works(creds) is True
    assert await refresh_works(creds) is False
    assert await refresh_works(creds) is None
    assert await refresh_works({}) is None                   # nothing to refresh with: unknown, not dead


async def _resolved(value):
    return value
