"""Token savings: the Claude Code settings Milo writes into its own profile (server.install_token_settings)."""

import importlib
import json
import os
import uuid

import pytest


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    (data / "config.json").write_text(json.dumps({"token": "t", "whisper_model": "/nonexistent",
                                                  "library_dir": str(data / "lib"), "browser_headless": True}))
    os.environ["MILO_DATA_DIR"], os.environ["MILO_KEYCHAIN_SERVICE"] = str(data), f"Milo-tok-{uuid.uuid4().hex[:8]}"
    import server
    yield importlib.reload(server)
    os.environ.pop("MILO_DATA_DIR"), os.environ.pop("MILO_KEYCHAIN_SERVICE")


def settings(srv):
    return json.loads((srv.CLAUDE_DIR / "settings.json").read_text())


def test_profile_gets_the_token_settings(srv):
    s = settings(srv)
    assert s["autoCompactWindow"] == 140_000
    assert set(srv.DENIED_TOOLS) <= set(s["permissions"]["deny"])
    assert all(s["skillOverrides"][k] == "off" for k in srv.SKILLS_OFF)
    assert any("guard.py" in m["hooks"][0]["command"] for m in s["hooks"]["PreToolUse"])   # the guard stays
    # Milo needs these: subagents, answers to them, and the document skills
    assert not {"Task", "Agent", "SendMessage", "TaskStop", "Bash", "Read", "WebSearch"} & set(s["permissions"]["deny"])
    assert not {"anthropic-skills:xlsx", "anthropic-skills:pdf", "anthropic-skills:docx"} & set(s["skillOverrides"])


def test_token_settings_keep_other_settings_and_run_once(srv):
    path = srv.CLAUDE_DIR / "settings.json"
    s = settings(srv)
    s["permissions"]["deny"].append("WebFetch(domain:example.com)")
    s["skillOverrides"]["my-skill"] = "on"
    s["model"] = "x"
    path.write_text(json.dumps(s))
    srv.install_token_settings()
    srv.install_token_settings()
    after = settings(srv)
    assert after["model"] == "x" and after["skillOverrides"]["my-skill"] == "on"
    assert after["permissions"]["deny"].count("CronCreate") == 1 and "WebFetch(domain:example.com)" in after["permissions"]["deny"]
    mtime = path.stat().st_mtime_ns
    srv.install_token_settings()   # nothing to change: no write
    assert path.stat().st_mtime_ns == mtime


def test_compact_at_default(srv):
    assert srv.DEFAULTS["compact_at"] == 100_000
