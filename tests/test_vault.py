"""Saved accounts: domain rules, Keychain storage, and that secrets never land on disk."""

import json

import keyring
import pyotp
import pytest

from vault import host_matches, normalize_domain


@pytest.mark.parametrize("site,expected", [
    ("https://www.GitHub.com/login", "github.com"),
    ("github.com", "github.com"),
    ("accounts.google.com", "accounts.google.com"),
    ("http://127.0.0.1:8000/login.html", "127.0.0.1"),
])
def test_normalize_domain(site, expected):
    assert normalize_domain(site) == expected


@pytest.mark.parametrize("url,domain,ok", [
    ("https://github.com/login", "github.com", True),
    ("https://www.github.com/login", "github.com", True),
    ("https://gist.github.com/", "github.com", True),
    ("https://github.com.evil.com/login", "github.com", False),   # suffix trick
    ("https://evilgithub.com/", "github.com", False),             # prefix trick
    ("https://github.co/", "github.com", False),
    ("http://127.0.0.1:5000/login.html", "127.0.0.1", True),
    ("about:blank", "github.com", False),
    ("https://github.com/", "", False),
])
def test_host_matches(url, domain, ok):
    assert host_matches(url, domain) is ok


def test_add_stores_secrets_only_in_keychain(vault):
    acct = vault.add(domain="https://www.example.com", username="alex", password="s3cret!pw", label="Example")
    assert acct["domain"] == "example.com" and acct["policy"] == "ask" and "password" not in acct
    on_disk = vault.store.path.read_text()
    assert "s3cret!pw" not in on_disk
    assert keyring.get_password(vault.service, f"{acct['id']}:password") == "s3cret!pw"
    assert vault.secret(acct["id"], "password") == "s3cret!pw"
    assert vault.secret(acct["id"], "username") == "alex"
    assert oct(vault.store.path.stat().st_mode)[-3:] == "600"


def test_totp_code(vault):
    seed = pyotp.random_base32()
    acct = vault.add(domain="example.com", username="a", password="p", totp=seed.lower())
    assert acct["has_totp"] is True
    assert vault.secret(acct["id"], "totp") == pyotp.TOTP(seed).now()


@pytest.mark.parametrize("kwargs", [
    {"domain": "", "username": "a", "password": "p"},
    {"domain": "x.com", "username": "", "password": "p"},
    {"domain": "x.com", "username": "a", "password": ""},
    {"domain": "x.com", "username": "a", "password": "p", "policy": "sometimes"},
    {"domain": "x.com", "username": "a", "password": "p", "totp": "not base32 !!"},
])
def test_add_rejects_bad_input(vault, kwargs):
    with pytest.raises(Exception):
        vault.add(**kwargs)
    assert vault.accounts() == []


def test_update_and_delete(vault):
    acct = vault.add(domain="example.com", username="a", password="old")
    vault.update(acct["id"], policy="auto", password="new")
    assert vault.get(acct["id"])["policy"] == "auto"
    assert vault.secret(acct["id"], "password") == "new"
    assert vault.delete(acct["id"]) is True
    assert keyring.get_password(vault.service, f"{acct['id']}:password") is None
    assert vault.delete(acct["id"]) is False


def test_for_url_and_matches(vault):
    a = vault.add(domain="example.com", username="a", password="p")
    vault.add(domain="other.org", username="b", password="q")
    assert [x["id"] for x in vault.for_url("https://login.example.com/")] == [a["id"]]
    assert vault.matches(a["id"], "https://example.com/") and not vault.matches(a["id"], "https://other.org/")
    json.loads(vault.store.path.read_text())  # valid JSON
