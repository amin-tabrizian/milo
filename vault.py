"""Saved accounts. Metadata lives in a JSON file; passwords and 2FA secrets live only in the macOS Keychain."""

import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import keyring
import pyotp

from features import JsonFile

PUBLIC = ("id", "label", "domain", "username", "policy", "has_totp", "created", "last_used")
POLICIES = ("ask", "auto")


def normalize_domain(site: str) -> str:
    """'https://www.GitHub.com/login' -> 'github.com'."""
    site = site.strip().lower()
    host = urlparse(site if "://" in site else f"https://{site}").hostname or ""
    return host.removeprefix("www.")


def host_matches(url: str, domain: str) -> bool:
    """True when the page's host is the account's domain or one of its subdomains."""
    host = (urlparse(url).hostname or "").lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


class Vault:
    def __init__(self, path: Path, service: str = "Milo"):
        self.store = JsonFile(path, [])
        self.service = service
        if path.exists():
            os.chmod(path, 0o600)

    def _save(self) -> None:
        self.store.save()
        os.chmod(self.store.path, 0o600)

    def accounts(self) -> list[dict]:
        return [{k: a.get(k) for k in PUBLIC} for a in self.store.data]

    def get(self, aid: str) -> dict | None:
        return next((a for a in self.store.data if a["id"] == aid), None)

    def add(self, *, domain: str, username: str, password: str, label: str = "", totp: str = "",
            policy: str = "ask") -> dict:
        domain = normalize_domain(domain)
        if not domain or not username or not password:
            raise ValueError("site, username and password are required")
        if policy not in POLICIES:
            raise ValueError("policy must be 'ask' or 'auto'")
        totp = totp.replace(" ", "").upper()
        if totp:
            pyotp.TOTP(totp).now()  # raises on an invalid base32 secret
        acct = {"id": uuid.uuid4().hex[:12], "label": label.strip() or domain, "domain": domain,
                "username": username.strip(), "policy": policy, "has_totp": bool(totp),
                "created": time.time(), "last_used": None}
        keyring.set_password(self.service, f"{acct['id']}:password", password)
        if totp:
            keyring.set_password(self.service, f"{acct['id']}:totp", totp)
        self.store.data.append(acct)
        self._save()
        return {k: acct[k] for k in PUBLIC}

    def update(self, aid: str, **fields) -> dict:
        acct = self.get(aid)
        if not acct:
            raise KeyError(aid)
        if fields.get("policy") is not None:
            if fields["policy"] not in POLICIES:
                raise ValueError("policy must be 'ask' or 'auto'")
            acct["policy"] = fields["policy"]
        for key in ("label", "username"):
            if fields.get(key):
                acct[key] = fields[key].strip()
        if fields.get("domain"):
            acct["domain"] = normalize_domain(fields["domain"])
        if fields.get("password"):
            keyring.set_password(self.service, f"{aid}:password", fields["password"])
        if fields.get("totp"):
            totp = fields["totp"].replace(" ", "").upper()
            pyotp.TOTP(totp).now()
            keyring.set_password(self.service, f"{aid}:totp", totp)
            acct["has_totp"] = True
        self._save()
        return {k: acct[k] for k in PUBLIC}

    def delete(self, aid: str) -> bool:
        acct = self.get(aid)
        if not acct:
            return False
        for kind in ("password", "totp"):
            try:
                keyring.delete_password(self.service, f"{aid}:{kind}")
            except keyring.errors.PasswordDeleteError:
                pass
        self.store.data = [a for a in self.store.data if a["id"] != aid]
        self._save()
        return True

    def matches(self, aid: str, url: str) -> bool:
        acct = self.get(aid)
        return bool(acct) and host_matches(url, acct["domain"])

    def for_url(self, url: str) -> list[dict]:
        return [{k: a[k] for k in PUBLIC} for a in self.store.data if host_matches(url, a["domain"])]

    def secret(self, aid: str, field: str) -> str | None:
        """field: 'username' (from metadata), 'password' or 'totp' (a fresh 6-digit code)."""
        acct = self.get(aid)
        if not acct:
            return None
        if field == "username":
            return acct["username"]
        if field == "password":
            return keyring.get_password(self.service, f"{aid}:password")
        if field == "totp":
            seed = keyring.get_password(self.service, f"{aid}:totp")
            return pyotp.TOTP(seed).now() if seed else None
        raise ValueError(field)

    def touch(self, aid: str) -> None:
        acct = self.get(aid)
        if acct:
            acct["last_used"] = time.time()
            self._save()
