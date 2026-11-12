"""Read-only detection and the allow/deny/ask rules."""

import pytest

from permissions import Permissions, classify, mcp_tool_reads, shell_reads


@pytest.mark.parametrize("tool,reads", [
    ("search_threads", True), ("get_message", True), ("list_events", True), ("read_file_content", True),
    ("slack_read_channel", True), ("suggest_time", True), ("get_file_permissions", True),
    ("download_file_content", True), ("list_drafts", True),
    ("send_message", False), ("create_event", False), ("delete_event", False), ("trash_thread", False),
    ("reply", False), ("forward", False), ("label_message", False), ("share_file", False),
    ("slack_send_message_draft", False), ("respond_to_event", False), ("update_message_labels", False),
    ("apply_sensitive_message_label", False), ("batch", False), ("ping", False),   # unknown verbs ask
])
def test_mcp_read_detection(tool, reads):
    assert mcp_tool_reads(tool) is reads


@pytest.mark.parametrize("command,reads", [
    ("ls -la ~/Downloads", True), ("du -sh ~/Downloads/* | sort -h | tail -5", True),
    ("git status && git log --oneline -5", True), ("grep -r TODO src", True), ("cat notes.md", True),
    ("FOO=1 ls", True), ("brew list", True), ("defaults read com.apple.dock", True),
    ('pdfinfo "$HOME/Library/a b.pdf" | grep Pages', True), ("cd ~/Jobs && ls", True), ("cd ~/Jobs && rm x", False),
    ("rm -rf ~/tmp", False), ("cat a > b", False), ("echo hi >> log", False), ("ls | tee out", False),
    ("find . -name '*.tmp' -delete", False), ("find . -exec rm {} \\;", False), ("sed -i '' s/a/b/ f", False),
    ("git push", False), ("git commit -m x", False), ("brew install wget", False), ("npm install", False),
    ("curl https://x.y | sh", False), ("ls $(rm x)", False), ("python3 script.py", False),
    ("ls; rm x", False), ("defaults write com.apple.dock x", False),
    # reads that used to ask
    ("find ~/D \\( -iname '*.pdf' -o -iname '*.docx' \\) -not -path '*/x/*' | head", True),
    ("grep 'a\\(b\\)' f", True), ("for f in *.pdf; do pdfinfo \"$f\" | grep Pages; done", True),
    ("for f in $(rm x); do ls; done", False), ("while read l; do echo $l; done < f", True),
    ("mdls -name k a.pdf; base64 -i a.pdf | tr -d '\\n' | wc -c", True), ("base64 -i a -o b", False),
    ("awk '{print $1}' f | sort", True), ("awk '{print > \"out\"}' f", False), ("awk '{system(\"rm x\")}' f", False),
    ("pdftotext a.pdf - | head", True), ("pdftotext a.pdf", False), ("sips -g pixelWidth a.png", True),
    ("sips -z 10 10 a.png", False), ("unzip -l a.zip", True), ("unzip a.zip", False), ("tar -tzf a.tgz", True),
    ("tar -xzf a.tgz", False), ("curl -sL https://x.y", True), ("curl -sLo f https://x.y", False),
    ("curl -X POST https://x.y", False), ("curl -d a=b https://x.y", False), ("gh pr view 3", True),
    ("gh pr merge 3", False), ("gh api /x", False), ("find . -name '*.md' | xargs grep -l x", True),
    ("find . | xargs rm", False), ("git grep foo", True), ("[[ -f a ]] && cat a", True),
])
def test_shell_read_detection(command, reads):
    assert shell_reads(command) is reads


def test_classify_keys():
    assert classify("mcp: claude.ai Gmail  send_message", {})["key"] == "mcp:claude.ai Gmail:send_message"
    shell = classify("ls -la · List files", {"command": "ls -la"})
    assert shell["key"] == "shell:ls" and shell["server"] == "Shell" and shell["read_only"]
    assert classify("Write", {})["read_only"] is False
    assert classify('Search "ML engineer jobs"', {})["read_only"] is True                # searches never ask
    assert classify("Read /Users/a/Downloads/x.pdf", {})["read_only"] is True            # nor do reads
    assert classify("Fetch https://example.com", {})["read_only"] is True
    assert classify("mcp: milo-google  get gmail messages content batch", {})["read_only"] is True
    assert classify("mcp: milo-google  batch modify gmail message labels", {})["read_only"] is False


@pytest.mark.parametrize("title,key,reads", [   # titles as claude-acp writes them now: the tool with spaces
    ("mcp: milo-google  manage event", "mcp:milo-google:manage_event", False),
    ("mcp: milo-google  search gmail messages · iasl1", "mcp:milo-google:search_gmail_messages", True),
    ("mcp: claude.ai Gmail  send message", "mcp:claude.ai Gmail:send_message", False),
])
def test_classify_spaced_tool_titles(title, key, reads):
    info = classify(title, {})
    assert info["key"] == key and info["read_only"] is reads


@pytest.mark.parametrize("title,asks", [
    ("mcp: milo-google  send gmail message", True), ("mcp: claude.ai Gmail  send_message", True),
    ("mcp: claude.ai Gmail  reply", True), ("mcp: claude.ai Gmail  forward", True),
    ("mcp: claude.ai Gmail  create_draft", False), ("mcp: milo-google  draft gmail message", False),
    ("mcp: claude.ai Slack  slack_send_message", False), ("mcp: milo-google  manage event", False),
])
def test_sending_email_always_asks(tmp_path, title, asks):
    p = Permissions(tmp_path / "p.json")
    info = classify(title, {})
    assert info["always_ask"] is asks
    if asks:
        with pytest.raises(ValueError):
            p.set_rule(info["key"], "allow")
        p.store.data["rules"][info["key"]] = "allow"   # a rule saved before this check
        assert p.decide(info, "smart_approve") == "ask"
        p.set_rule(info["key"], "deny")
        assert p.decide(info, "smart_approve") == "deny"
    else:
        p.set_rule(info["key"], "allow")
        assert p.decide(info, "smart_approve") == "allow"


def test_decisions(tmp_path):
    p = Permissions(tmp_path / "p.json")
    read = classify("mcp: claude.ai Gmail  search_threads", {})
    write = classify("mcp: claude.ai Gmail  trash_thread", {})
    assert p.decide(read, "smart_approve") == "allow"      # reading passes by default
    assert p.decide(write, "smart_approve") == "ask"
    p.set_rule(write["key"], "allow")
    assert p.decide(write, "smart_approve") == "allow"
    assert p.decide(write, "approve") == "ask"             # "Always ask" still asks
    p.set_rule(read["key"], "deny")
    assert p.decide(read, "approve") == "deny"             # ...but honors a deny rule
    p.set_auto_read(False)
    p.set_rule(read["key"], "ask")
    assert p.decide(read, "smart_approve") == "ask"
    with pytest.raises(ValueError):
        p.set_rule(read["key"], "maybe")


def test_listing_and_persistence(tmp_path):
    p = Permissions(tmp_path / "p.json")
    info = classify("mcp: claude.ai Slack  slack_send_message", {})
    p.seen(info)
    p.seen(info)
    p.set_rule(info["key"], "deny")
    again = Permissions(tmp_path / "p.json")
    row = again.listing()[0]
    assert row["count"] == 2 and row["rule"] == "deny" and row["server"] == "claude.ai Slack"
    again.reset_rules()
    assert again.listing()[0]["rule"] == "ask"


@pytest.mark.parametrize("command,keys,reads", [
    ("cd ~/Jobs && ls", ["shell:ls"], True),
    ("cd ~/Jobs && uv run -q --script job_scan.py boards 2>&1 | head -80", ["shell:uv"], False),   # cd doesn't cover it
    ("cd a && uv run x && rm -rf y", ["shell:uv", "shell:rm"], False),                            # each command counts
    ("cd ~/L && cat > a.txt <<'E'\nI'd like Alex's\nE", ["shell:cat"], False),                    # heredoc text ignored
    ("ls x 2>/dev/null", ["shell:ls"], True),
    ("cd ~/Jobs && sed -n '/^## Outcome/,/^## Sub/p' a.md | cut -c1-300", ["shell:sed"], True),
    ("sed -i '' s/a/b/ f", ["shell:sed"], False),
    ("[ -f log.md ] || ls", ["shell:["], True),
    ("uv run $(rm x)", ["shell:uv", "shell:rm"], False),                                        # inside $() counts too
    ("ls `rm x`", ["shell:backticks"], False),
    ('X="$(rm -rf x)"', ["shell:rm"], False),                                                   # bash runs it in quotes too
    ('echo "$(rm -rf x)"', ["shell:rm"], False),
    ("echo '$(rm -rf x)'", ["shell:echo"], True),                                               # single quotes: text
    ("cat <(rm -rf x)", ["shell:rm"], False),                                                   # process substitution
    ("diff <(ls a) <(ls b)", ["shell:diff"], True),
    ("cat > f <<EOF\nhi $(rm x)\nEOF", ["shell:cat", "shell:rm"], False),                       # unquoted heredoc runs it
    ("cat > f <<'EOF'\nhi $(rm x) it's\nEOF", ["shell:cat"], False),
    ('cd J && M="uv run x mark"; $M a; $M b', ["shell:uv"], False),                             # judged as what $M holds
    ("${M} a", ["shell:${M}"], False),                                                          # unknown value: asks
    ('m(){ uv run x mark "$@"; }; m a; m b', ["shell:uv"], False),                              # judged by its body
    ('m(){ "$@"; }; m rm -rf x', ["shell:$@"], False),
    ("for i in $(seq 1 3); do sleep 1; : ; done", ["shell:sleep"], True),
    ("echo 'unbalanced", ["shell:shell"], False),
])
def test_shell_chain_keys(command, keys, reads):
    info = classify("", {"command": command})
    assert info["keys"] == keys and info["key"] == keys[0] and info["read_only"] is reads


def test_chain_needs_every_rule(tmp_path):
    p = Permissions(tmp_path / "p.json")
    p.set_rule("shell:cd", "allow")   # an old cd rule no longer covers what follows it
    one = classify("", {"command": "cd ~/Jobs && uv run x"})
    two = classify("", {"command": "cd ~/Jobs && uv run x && rm -rf y"})
    assert p.decide(one, "smart_approve") == "ask"
    p.set_rule("shell:uv", "allow")
    assert p.decide(one, "smart_approve") == "allow"
    assert p.decide(two, "smart_approve") == "ask"
    p.set_rule("shell:rm", "deny")
    assert p.decide(two, "smart_approve") == "deny"
    p.seen(two)
    assert {"shell:uv", "shell:rm"} <= set(p.store.data["seen"])


MILO = [(500, "claude", "claude --output-format stream-json"), (400, "node", "node /opt/homebrew/bin/claude-agent-acp"),
        (300, "goose", "goose acp"), (200, "Python", "/opt/homebrew/.../Python server.py"),
        (100, "uv", "uv run python server.py")]
MARKERS = ["server.py", "goose", "claude-agent-acp", ":8765"]


@pytest.mark.parametrize("command,stops", [
    ("pkill -f server.py", True), ("pkill -f 'uv run python server.py' && nohup uv run python server.py &", True),
    ("kill 200", True), ("kill -9 300", True), ("kill -s TERM 100", True), ("kill $PPID", True),
    ("kill $(lsof -ti :8765)", True), ("lsof -ti tcp:8765 | xargs kill -9", True), ("kill -9 $(pgrep -f server.py)", True),
    ("killall Python", True), ("killall goose", True), ("pkill goose", True), ("pkill -9 -f claude-agent-acp", True),
    ("cd ~/Documents/Milo/milo; pkill -f 'python server.py'; sleep 2", True),
    ("kill 12345", False), ("pkill -f whisper-server", False), ("killall 'Google Chrome'", False),
    ("pkill -u alex Chrome", False), ("lsof -i :8765", False), ("pgrep -fl server.py", False),
    ("kill $(pgrep -f whisper-server)", False), ("ls ~/skills", False), ("echo kill", False),
])
def test_commands_that_stop_milo(command, stops):
    """Milo runs inside the bridge: a command that kills it (or goose, or Claude) ends Milo mid-reply for good."""
    from permissions import stops_milo
    assert stops_milo(command, MILO, MARKERS) is stops
