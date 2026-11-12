"""Shared pieces for Milo's MCP proxies: an upstream stdio MCP client and a bearer-protected HTTP endpoint."""

import asyncio
import logging
import secrets
from typing import Callable

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

log = logging.getLogger("mcp-proxy")

Timeout = float | Callable[[str, dict], float] | None


class UpstreamTimeout(Exception):
    """The upstream server did not answer a call in time. It has been restarted; the call was not retried."""


class Upstream:
    """One upstream MCP server over stdio. The client lives in its own task: anyio contexts must exit where entered."""

    def __init__(self, name: str, command: str, args: list[str], env: Callable[[], dict] | None = None,
                 exclude: set[str] = frozenset(), annotate: Callable[[types.Tool], types.Tool] | None = None,
                 cwd: str | None = None, timeout: Timeout = None):
        self.name, self.command, self.args, self.cwd = name, command, args, cwd
        self.timeout = timeout   # seconds per call (or a function of the call); None waits for ever
        self.env = env or (lambda: {})
        self.exclude, self.annotate = exclude, annotate or (lambda t: t)
        self.session: ClientSession | None = None
        self.tools: list[types.Tool] = []
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._restart = asyncio.Event()

    async def start(self, timeout: float = 180) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), timeout)

    async def restart(self) -> None:
        self._ready.clear()
        self._restart.set()
        await self.start()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task, self.session = None, None
        self._ready.clear()

    async def call(self, name: str, args: dict) -> types.CallToolResult:
        if self.session is None:
            await self.start()
        try:
            return await self._call(name, args)
        except UpstreamTimeout:
            raise
        except Exception:
            log.warning("%s failed; restarting it once", self.name)
            await self.restart()
            return await self._call(name, args)

    async def _call(self, name: str, args: dict) -> types.CallToolResult:
        """A call that never answers held the caller until the client's 300 s idle timeout (2026-10-27: Playwright
        MCP hung on one wedged tab). Give up sooner and restart the server; don't retry, as a click could run twice."""
        limit = self.timeout(name, args) if callable(self.timeout) else self.timeout
        try:
            return await asyncio.wait_for(self.session.call_tool(name, args), limit)
        except asyncio.TimeoutError:
            log.warning("%s: %s got no answer in %g s; restarting it", self.name, name, limit)
            try:
                await self.restart()
            except Exception:
                log.exception("%s did not come back", self.name)   # the next call starts it again
            raise UpstreamTimeout(f"{name} got no answer in {limit:g} s") from None

    async def _run(self) -> None:
        while True:
            params = StdioServerParameters(command=self.command, args=self.args, env=self.env() or None, cwd=self.cwd)
            try:
                async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.tools = [self.annotate(t) for t in tools if t.name not in self.exclude]
                    self.session = session
                    self._restart.clear()
                    self._ready.set()
                    log.info("%s ready: %d tools", self.name, len(self.tools))
                    await self._restart.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s stopped", self.name)
                await asyncio.sleep(2)
            finally:
                self.session = None
                self._ready.clear()


def session_manager(server: Server) -> StreamableHTTPSessionManager:
    return StreamableHTTPSessionManager(
        app=server, stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]))


class BearerEndpoint:
    """ASGI endpoint: checks 'Authorization: Bearer <key>' and hands the request to the MCP transport."""

    def __init__(self, manager: StreamableHTTPSessionManager, key: str):
        self.key = key
        self.inner = StreamableHTTPASGIApp(manager)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            if not secrets.compare_digest(auth, f"Bearer {self.key}"):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.inner(scope, receive, send)
