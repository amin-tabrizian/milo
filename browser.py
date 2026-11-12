"""Milo's own Chrome window: launch, live view (CDP screencast), remote input, takeover and a per-task lock."""

import asyncio
import base64
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from playwright.async_api import Browser, Page, async_playwright

log = logging.getLogger("browser")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FOCUSED_INPUT_JS = """() => {
  const e = document.activeElement;
  if (!e) return null;
  if (e.tagName === 'IFRAME') return 'iframe';
  if (e.tagName === 'TEXTAREA') return 'textarea';
  if (e.tagName === 'INPUT') return (e.type || 'text').toLowerCase();
  if (e.isContentEditable) return 'contenteditable';
  return null;
}"""

Emit = Callable[[dict], Awaitable[None]]


class BrowserError(RuntimeError):
    pass


class BrowserManager:
    def __init__(self, profile: Path, port: int = 9333, headless: bool = False, emit: Emit | None = None,
                 working: Callable[[], bool] = lambda: False):
        self.profile = profile
        self.port = port
        self.headless = headless
        self.emit = emit
        self.working = working   # Milo is at work (a chat runs, the feed reads): a tab that opens now is Milo's
        self.cdp_url = f"http://127.0.0.1:{port}"
        self.proc: asyncio.subprocess.Process | None = None
        self._pw = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._ids: dict[Page, str] = {}
        self._milos: set[Page] = set()   # tabs that opened while Milo worked (close_milos_tabs)
        # takeover
        self.controller = "milo"
        self.reason = ""
        self.released = asyncio.Event()
        self.released.set()
        # one task drives the browser at a time
        self._lock = asyncio.Lock()
        self.lock_owner: str | None = None
        # live view
        self.viewers: set[asyncio.Queue] = set()
        self._cast_session = None
        self._cast_page: Page | None = None
        self.meta = {"w": 1280, "h": 800}

    # lifecycle

    async def _alive(self) -> bool:
        try:
            async with httpx.AsyncClient() as c:
                return (await c.get(f"{self.cdp_url}/json/version", timeout=1)).status_code == 200
        except httpx.HTTPError:
            return False

    async def start(self) -> None:
        if not await self._alive():
            if not Path(CHROME).exists():
                raise BrowserError("Google Chrome is not installed")
            self.profile.mkdir(parents=True, exist_ok=True)
            os.chmod(self.profile, 0o700)
            args = [CHROME, f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
                    "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                    "--window-size=1280,900", "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding", "--disable-features=Translate"]
            if self.headless:
                args.append("--headless=new")
            # its own session: the browser (and its logins) survive a bridge restart
            self.proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL,
                                                             stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            for _ in range(60):
                if await self._alive():
                    break
                await asyncio.sleep(0.25)
            else:
                raise BrowserError("Chrome did not open its debugging port")
        self._pw = self._pw or await async_playwright().start()
        self.browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        self.browser.on("disconnected", lambda *_: self._on_disconnect())
        ctx = self.browser.contexts[0]
        for p in ctx.pages:
            self._watch(p)
        ctx.on("page", self._on_new_page)
        if not ctx.pages:
            await ctx.new_page()
        self.page = self.page if self.page in ctx.pages else ctx.pages[-1]
        log.info("browser ready on %s (%s)", self.cdp_url, "headless" if self.headless else "window")
        await self._changed()

    async def ensure_running(self) -> None:
        if not self.browser or not self.browser.is_connected():
            await self.start()

    async def stop(self, close_chrome: bool = False) -> None:
        await self._stop_cast()
        if self.browser and self.browser.is_connected():
            if close_chrome:
                try:
                    await self.browser.close()
                except Exception:
                    pass
        if close_chrome and self.proc and self.proc.returncode is None:
            self.proc.terminate()
        if self._pw:
            await self._pw.stop()
            self._pw = None
        self.browser = None

    async def reset(self) -> None:
        """Close Chrome and delete the profile: logs Milo out of every site."""
        await self.stop(close_chrome=True)
        for _ in range(40):
            if not await self._alive():
                break
            await asyncio.sleep(0.25)
        shutil.rmtree(self.profile, ignore_errors=True)
        self.page = None
        self._ids.clear()
        self._milos.clear()
        await self.start()

    def _on_disconnect(self) -> None:
        self.browser = None
        asyncio.get_event_loop().create_task(self._changed())

    # pages

    def _watch(self, page: Page) -> None:
        self._ids.setdefault(page, uuid.uuid4().hex[:8])
        page.on("framenavigated", lambda frame: frame == page.main_frame and asyncio.ensure_future(self._activate(page)))
        page.on("close", lambda _: asyncio.ensure_future(self._closed(page)))

    def _on_new_page(self, page: Page) -> None:
        self._watch(page)
        if self.working():
            self._milos.add(page)
        asyncio.ensure_future(self._activate(page))

    async def _activate(self, page: Page) -> None:
        if page.is_closed():
            return
        if page is not self.page:
            self.page = page
            if self.viewers:
                await self._start_cast()
        await self._changed()

    async def _closed(self, page: Page) -> None:
        self._ids.pop(page, None)
        self._milos.discard(page)
        if page is self.page:
            pages = self.pages()
            self.page = pages[-1] if pages else None
            if self.viewers:
                await self._start_cast()
        await self._changed()

    async def close_milos_tabs(self) -> int:
        """Close the tabs that opened while Milo worked (Apply links that open a new tab, browser_tabs new), once it
        is idle. They were never closed: 37 Chrome processes held 9 GB when the Mac hung (2026-10-21). The tab on
        show stays, and so does the last tab (Chrome without a window breaks the browser tools). The user's own
        tabs, opened while Milo was idle, stay too."""
        tabs = [p for p in self._milos if p is not self.page and not p.is_closed()]
        tabs = tabs[:max(0, len(self.pages()) - 1)]
        for page in tabs:
            try:
                await page.close()
            except Exception as e:
                log.warning("couldn't close tab %s: %s", page.url, e)
        return len(tabs)

    async def reopen_stuck_tabs(self, wait: float = 3) -> list[str]:
        """Reopen the tabs that don't answer Playwright, at the same address, and return their titles. One tab the
        user opened from Chrome's address bar (a Google search, 2026-10-27) never finished attaching: Chrome answered
        for it, but every Playwright call that touched it, and so every browser tool, waited for ever."""
        pages = self.pages()
        if not pages:
            return []

        async def answers(page: Page) -> bool:
            try:
                await asyncio.wait_for(page.title(), wait)
                return True
            except Exception:
                return False

        ok = await asyncio.gather(*(answers(p) for p in pages))
        stuck = [p for p, good in zip(pages, ok) if not good]
        if not stuck:
            return []
        # Playwright doesn't know a stuck tab's address (its url is ''), so ask Chrome: the stuck tabs are the
        # targets left once the answering tabs are matched off by url.
        cdp = await self.browser.new_browser_cdp_session()
        try:
            targets = [t for t in (await cdp.send("Target.getTargets"))["targetInfos"]
                       if t["type"] == "page" and t.get("subtype") != "prerender"]
            left = [p.url for p, good in zip(pages, ok) if good]
            unknown = []
            for t in targets:
                if t["url"] in left:
                    left.remove(t["url"])
                else:
                    unknown.append(t)
            if len(unknown) != len(stuck):
                log.warning("%d tabs don't answer, but %d tabs are unmatched; leaving them", len(stuck), len(unknown))
                return []
            ctx = self.browser.contexts[0]
            for t in unknown:
                log.warning("reopening stuck tab %s", t["url"])
                async with ctx.expect_page(timeout=wait * 3000) as new:
                    await cdp.send("Target.createTarget", {"url": t["url"] or "about:blank", "background": True})
                self._milos.discard(await new.value)   # the user's tab, not Milo's: close_milos_tabs leaves it
                await cdp.send("Target.closeTarget", {"targetId": t["targetId"]})
            # Chrome reports the close a moment later; wait for it, so pages() and the tab on show are right
            for _ in range(int(wait * 10)):
                if all(p.is_closed() for p in stuck):
                    break
                await asyncio.sleep(0.1)
            return [t["title"] or t["url"] for t in unknown]
        finally:
            try:
                await cdp.detach()
            except Exception:
                pass

    def pages(self) -> list[Page]:
        if not self.browser or not self.browser.contexts:
            return []
        return [p for p in self.browser.contexts[0].pages if not p.is_closed()]

    async def select_tab(self, tab_id: str) -> None:
        page = next((p for p, i in self._ids.items() if i == tab_id and not p.is_closed()), None)
        if not page:
            raise BrowserError("tab not found")
        await self.show(page)

    async def show(self, page: Page) -> None:
        """Make a tab the active one, e.g. again after a background job (the feed) closed its own tab."""
        await page.bring_to_front()
        await self._activate(page)

    # state

    def state(self) -> dict:
        tabs = []
        for p in self.pages():
            tabs.append({"id": self._ids.get(p), "url": p.url, "active": p is self.page})
        return {"running": bool(self.browser and self.browser.is_connected()), "url": self.page.url if self.page else "",
                "tabs": tabs, "controller": self.controller, "reason": self.reason, "busy": self.lock_owner,
                "w": self.meta["w"], "h": self.meta["h"]}

    async def _changed(self) -> None:
        state = self.state()
        for q in list(self.viewers):
            self._offer(q, {"t": "state", "state": state})
        if self.emit:
            await self.emit(state)

    # takeover

    async def take(self, reason: str = "") -> None:
        self.controller, self.reason = "user", reason
        self.released.clear()
        await self._changed()

    async def release(self) -> None:
        self.controller, self.reason = "milo", ""
        self.released.set()
        await self._changed()

    async def wait_for_milo_turn(self) -> bool:
        """Block while the user has control. Returns True when it had to wait."""
        if self.released.is_set():
            return False
        await self.released.wait()
        return True

    # per-task lock

    async def acquire(self, owner: str) -> None:
        if self.lock_owner == owner:
            return
        await self._lock.acquire()
        self.lock_owner = owner
        await self._changed()

    async def release_lock(self, owner: str) -> None:
        if self.lock_owner == owner and self._lock.locked():
            self.lock_owner = None
            self._lock.release()
            await self._changed()

    # credentials: type into whatever input has focus, never through the model

    async def focused_input(self) -> tuple[Page, str] | None:
        candidates = [self.page] + [p for p in self.pages() if p is not self.page]
        for page in candidates:
            if not page or page.is_closed():
                continue
            try:
                kind = await page.evaluate(FOCUSED_INPUT_JS)
            except Exception:
                continue
            if kind:
                return page, kind
        return None

    async def type_secret(self, page: Page, text: str) -> None:
        await page.keyboard.insert_text(text)

    # live view

    @staticmethod
    def _offer(q: asyncio.Queue, item) -> None:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(item)

    async def add_viewer(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=3)
        self.viewers.add(q)
        await self.ensure_running()
        if self.page:
            try:
                shot = await self.page.screenshot(type="jpeg", quality=60)
                self._offer(q, shot)
            except Exception:
                pass
        self._offer(q, {"t": "state", "state": self.state()})
        if len(self.viewers) == 1 or self._cast_page is not self.page:
            await self._start_cast()
        return q

    async def remove_viewer(self, q: asyncio.Queue) -> None:
        self.viewers.discard(q)
        if not self.viewers:
            await self._stop_cast()

    async def _start_cast(self) -> None:
        await self._stop_cast()
        if not self.page or self.page.is_closed():
            return
        page = self.page
        session = await page.context.new_cdp_session(page)
        session.on("Page.screencastFrame", lambda params: asyncio.ensure_future(self._frame(session, params)))
        await session.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1280,
                                                    "maxHeight": 1600, "everyNthFrame": 1})
        self._cast_session, self._cast_page = session, page

    async def _stop_cast(self) -> None:
        session, self._cast_session, self._cast_page = self._cast_session, None, None
        if session:
            try:
                await session.send("Page.stopScreencast")
                await session.detach()
            except Exception:
                pass

    async def _frame(self, session, params: dict) -> None:
        try:
            await session.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            return
        meta = params.get("metadata", {})
        size = {"w": round(meta.get("deviceWidth", self.meta["w"])), "h": round(meta.get("deviceHeight", self.meta["h"]))}
        if size != self.meta:
            self.meta = size
            for q in list(self.viewers):
                self._offer(q, {"t": "meta", **size})
        frame = base64.b64decode(params["data"])
        for q in list(self.viewers):
            self._offer(q, frame)

    # remote input (only while the user has control)

    async def tap(self, x: float, y: float) -> None:
        await self.page.mouse.click(x, y)

    async def wheel(self, x: float, y: float, dy: float) -> None:
        await self.page.mouse.move(x, y)
        await self.page.mouse.wheel(0, dy)

    async def text(self, s: str) -> None:
        await self.page.keyboard.insert_text(s)

    async def key(self, name: str) -> None:
        if name not in {"Enter", "Backspace", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
                        "Delete", "Home", "End", "PageUp", "PageDown", "Space"}:
            raise BrowserError(f"key not allowed: {name}")
        await self.page.keyboard.press(" " if name == "Space" else name)

    async def navigate(self, url: str) -> None:
        if "://" not in url:
            url = f"https://{url}"
        await self.ensure_running()
        await self.page.goto(url, wait_until="domcontentloaded")

    async def back(self) -> None:
        await self.page.go_back()

    async def reload(self) -> None:
        await self.page.reload()
