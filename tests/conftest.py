"""Shared fixtures. Unit tests need nothing running. e2e tests start a headless Chrome on port 9444."""

import functools
import http.server
import sys
import threading
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).parent / "site"
sys.path.insert(0, str(ROOT))

TEST_PASSWORD = "correct horse 42"   # the test site accepts this one (it only knows its SHA-256)


@pytest.fixture(scope="session")
def site_url():
    """The local test website on 127.0.0.1 (login, shop, human check)."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def vault(tmp_path):
    """A vault under a throwaway Keychain service; its Keychain entries are deleted afterwards."""
    from vault import Vault
    v = Vault(tmp_path / "accounts.json", service=f"Milo-test-{uuid.uuid4().hex[:8]}")
    yield v
    for acct in list(v.accounts()):
        v.delete(acct["id"])
