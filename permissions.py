"""Which tool calls Milo may make without asking. Read-only calls pass by default; the user's rules win."""

import re
import shlex
import time
from pathlib import Path

from features import JsonFile

READ_WORDS = {"get", "list", "search", "read", "query", "find", "fetch", "view", "show", "describe", "count", "check",
              "lookup", "suggest", "download", "browse", "inspect", "preview", "resolve", "status", "whoami", "info",
              "guide", "snapshot", "screenshot", "history", "recent", "metadata", "permissions"}
WRITE_WORDS = {"send", "create", "update", "delete", "trash", "untrash", "reply", "forward", "label", "unlabel", "share",
               "copy", "move", "add", "remove", "post", "respond", "schedule", "set", "write", "edit", "upload",
               "apply", "mark", "unmark", "draft", "invite", "rename", "archive", "publish", "submit", "pay",
               "purchase", "transfer", "execute", "run", "install", "uninstall", "complete", "reaction", "save",
               "modify"}   # not "batch": get_gmail_messages_content_batch only reads
SAFE_COMMANDS = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "find", "pwd", "wc", "which", "whereis",
                 "date", "cal", "du", "df", "file", "stat", "ps", "uname", "whoami", "id", "sw_vers", "mdfind", "mdls",
                 "echo", "printf", "sort", "uniq", "cut", "tr", "jq", "tree", "basename", "dirname", "realpath",
                 "readlink", "uptime", "hostname", "true", "column", "nl", "diff", "cmp", "shasum", "md5", "type",
                 "cd", "pdfinfo", "pdffonts", "sed", "[", "[[", "test", "read", "strings", "od", "hexdump", "zipinfo",
                 "otool", "nm", "ffprobe", "pgrep", "lsof", "w", "who", "locale", "vm_stat", "netstat", "ioreg",
                 "system_profiler", "tac", "rev", "fold", "fmt", "expand", "paste", "join", "comm", "look", "cksum",
                 "sha1sum", "sha256sum", "md5sum", "pbpaste", "getconf", "arch", "groups", "false", "seq", "xmllint",
                 ":", "sleep"}
SAFE_SUBCOMMANDS = {"git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame",
                            "describe", "tag", "grep", "shortlog", "cat-file", "rev-list", "ls-remote", "for-each-ref"},
                    "brew": {"list", "info", "search", "outdated", "--version", "config"},
                    "defaults": {"read", "read-type", "domains", "find"}, "npm": {"ls", "list", "view", "outdated"},
                    "pip": {"list", "show"}, "launchctl": {"list", "print", "version"}}
# Read-only unless one of these options writes or sends (letters of a short option group count too: -sO)
WRITE_OPTIONS = {"base64": {"-o", "--output"}, "xmllint": {"-o", "--output"}, "xattr": {"-w", "-d", "-c"},
                 "codesign": {"-s", "--sign", "-f", "--force", "--remove-signature"},
                 "curl": {"-o", "--output", "-O", "--remote-name", "--remote-name-all", "-d", "--data", "--data-raw",
                          "--data-binary", "--data-urlencode", "--json", "-F", "--form", "-T", "--upload-file", "-X",
                          "--request", "-K", "--config", "-c", "--cookie-jar", "-D", "--dump-header"}}
# Read-only only with one of these options
READ_OPTIONS = {"unzip": {"-l", "-Z", "-t", "-v", "-z", "-p"}, "plutil": {"-p", "-lint"}, "pmset": {"-g"},
                "textutil": {"-stdout"}, "pdfimages": {"-list"}, "top": {"-l"}, "scutil": {"--get", "--dns", "--proxy", "--nwi"}}
GH_READS = {"pr", "issue", "repo", "run", "release", "workflow", "gist"}, {"view", "list", "status", "diff", "checks"}
EMAIL_SEND_WORDS = {"send", "reply", "forward"}
# Claude Code's own read and search tools (web search: 'Search "query"', a web page: 'Fetch <url>')
READ_TOOLS = {"read", "view", "ls", "list", "search", "find", "grep", "glob", "fetch", "websearch", "webfetch",
              "notebookread"}
RULES = ("allow", "deny", "ask")


def classify(title: str, raw: dict) -> dict:
    """Describe a permission request: a stable key, a label for the UI, the server, and whether it only reads."""
    # "mcp: <server>  <tool>[ · <subject>]"; newer claude-acp writes the tool with spaces ("send gmail message")
    m = re.match(r"mcp:\s*(.+?)\s{2,}(.+?)(?:\s+·\s.*)?\s*$", title or "")
    if m:
        server, tool = m.group(1).strip(), re.sub(r"\s+", "_", m.group(2).strip())
        return {"key": f"mcp:{server}:{tool}", "label": tool.replace("_", " "), "server": server,
                "read_only": mcp_tool_reads(tool), "always_ask": sends_email(server, tool)}
    command = (raw or {}).get("command")
    if command:
        # A rule covers one command name; a chain passes only if each command in it is read-only or allowed
        needs = shell_needs(command)
        names = needs or [first_word(command)]
        keys = [f"shell:{n}" for n in names]
        return {"key": keys[0], "keys": keys, "label": f"Shell: {', '.join(names)}", "server": "Shell",
                "read_only": needs == []}
    name = (title or "Tool").split()[0]
    return {"key": f"tool:{name}", "label": name, "server": "Claude Code", "read_only": name.lower() in READ_TOOLS}


def mcp_tool_reads(tool: str) -> bool:
    words = set(re.split(r"[_\-.]", tool.lower()))
    return not (words & WRITE_WORDS) and bool(words & READ_WORDS)


def sends_email(server: str, tool: str) -> bool:
    """Mail that leaves the account. The user asked to approve each one, so no rule can allow it."""
    words = set(re.split(r"[_\-.]", tool.lower()))
    return bool(words & EMAIL_SEND_WORDS) and "mail" in f"{server} {tool}".lower()


def key_sends_email(key: str) -> bool:
    parts = key.split(":", 2)
    return len(parts) == 3 and parts[0] == "mcp" and sends_email(parts[1], parts[2])


SEPARATOR_CHARS = set(";&|\n()")
REDIRECT_OUT = {">", ">>", ">|", "&>", "&>>"}
SHELL_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
BACKTICK = re.compile(r"`")
LOOP_HEADS = {"for", "select", "case"}   # "for f in a b": words, not a command (the body is its own segment)
PAREN = ("\0lp\0", "\0rp\0")   # find's \( \) are words, not a subshell
NAME = re.compile(r"[A-Za-z_][\w-]*")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
VAR_CMD = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def strip_heredocs(command: str, live: list[str] | None = None) -> str:
    """Drop heredoc bodies: they are text for a command, not commands (an apostrophe in one broke parsing).
    Bodies of unquoted ones (<<EOF, where bash runs $(...)) go to `live`."""
    out, ends = [], []   # (delimiter, quoted)
    for line in command.split("\n"):
        if ends:
            if line.strip() == ends[0][0]:
                ends.pop(0)
            elif live is not None and not ends[0][1]:
                live.append(line)
            continue
        out.append(line)
        ends += [(m.group(2), bool(m.group(1))) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def pull_substitutions(text: str, quotes: bool = True) -> tuple[str, list[str]] | None:
    """Cut $(...), <(...) and >(...) out of a line, also inside double quotes, where shlex keeps them as words
    but bash runs them. The line keeps a placeholder word; the insides come back to be judged on their own.
    quotes=False: a heredoc body, where quote marks are plain text. None if a parenthesis is unbalanced."""
    out, inner, quote, i = [], [], None, 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        elif quotes and ch == "'" and quote is None:
            quote = "'"
        elif quotes and ch == '"':
            quote = None if quote == '"' else '"'
        elif ch in "$<>" and text[i + 1:i + 2] == "(" and text[i + 2:i + 3] != "(":   # not $(( )) arithmetic
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            if depth:
                return None
            inner.append(text[i + 2:j - 1])
            out.append("SUBST")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out), inner


def shell_segments(command: str) -> list[list[str]] | None:
    """The simple commands of a shell line, split on && || ; | & and newlines, with the commands inside $(...),
    <(...), >(...) and unquoted heredocs; None if it can't be parsed."""
    live = []
    pulled = pull_substitutions(strip_heredocs(command, live).replace("\\(", PAREN[0]).replace("\\)", PAREN[1]))
    if pulled is None:
        return None
    text, inner = pulled
    for body in live:
        got = pull_substitutions(body, quotes=False)
        if got is None:
            return None
        inner += got[1]
    lexer = shlex.shlex(text.replace("\\\n", " "), posix=True, punctuation_chars=";&|<>()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        toks = list(lexer)
    except ValueError:
        return None
    segments, current, funcs = [], [], set()
    for i, token in enumerate(toks):
        if token and set(token) <= SEPARATOR_CHARS:
            if len(current) == 1 and NAME.fullmatch(current[0]) and (token == "()" or toks[i:i + 2] == ["(", ")"]):
                funcs.add(current[0])   # m() { ...; }: its body is judged as its own commands, so calls to m pass
                current = []
            segments.append(current)
            current = []
        else:
            current.append(token.replace(PAREN[0], "(").replace(PAREN[1], ")"))
    segments.append(current)
    out, values = [], {}
    for tokens in segments:
        if tokens and all(ASSIGN.match(t) for t in tokens):
            values.update(ASSIGN.match(t).groups() for t in tokens)
        while tokens and (tokens[0] in SHELL_KEYWORDS or ASSIGN.match(tokens[0])):
            tokens = tokens[1:]   # FOO=bar cmd, then cmd, do cmd
        if tokens and (var := VAR_CMD.fullmatch(tokens[0])) and var[1] in values:
            try:   # M="uv run x"; $M a: judged as uv
                tokens = shlex.split(values[var[1]]) + tokens[1:]
            except ValueError:
                return None
        if tokens and tokens[0] not in {"fi", "done", "esac", "}"} | LOOP_HEADS | funcs:
            out.append(tokens)
    for sub in inner:
        segs = shell_segments(sub)
        if segs is None:
            return None
        out += segs
    return out


def short_flags(token: str) -> set[str]:
    """-sO -> {"-s", "-O"}"""
    return {f"-{c}" for c in token[1:]} if re.fullmatch(r"-[A-Za-z]{2,}", token) else set()


def segment_reads(tokens: list[str]) -> bool:
    cmd, args = Path(tokens[0]).name, tokens[1:]
    if any(t in REDIRECT_OUT and nxt != "/dev/null" for t, nxt in zip(tokens, tokens[1:] + [""])):
        return False
    if cmd == "find" and {"-delete", "-exec", "-execdir", "-ok", "-okdir"} & set(tokens):
        return False
    if cmd == "sed" and any(t.startswith("-i") or t.startswith("--in-place") for t in args):
        return False
    if cmd in SAFE_SUBCOMMANDS:
        sub = next((t for t in args if not t.startswith("-") or t == "--version"), "")
        return sub in SAFE_SUBCOMMANDS[cmd]
    if cmd in WRITE_OPTIONS:
        bad = WRITE_OPTIONS[cmd]
        return not any(t.split("=", 1)[0] in bad or short_flags(t) & bad for t in args)
    if cmd in READ_OPTIONS:
        return bool(set(args) & READ_OPTIONS[cmd])
    if cmd == "gh":
        return (len(args) > 1 and args[0] in GH_READS[0] and args[1] in GH_READS[1]) or args[:1] == ["search"] \
            or args[:2] == ["auth", "status"]
    if cmd == "awk":   # a program can write files or run commands
        return not ({"-f", "-i"} & set(args)) and not any(w in t for t in args for w in ("system", "getline", ">", "|"))
    if cmd == "pdftotext":   # writes a .txt next to the PDF unless the output is stdout
        return args[-1:] == ["-"]
    if cmd == "sips":   # -g reads properties; every other option changes the picture
        opts = [t for t in args if t.startswith("-")]
        return bool(opts) and all(t in {"-g", "--getProperty", "-1", "--oneLine"} for t in opts)
    if cmd == "tar":   # listing only
        mode = args[0].lstrip("-") if args else ""
        return "t" in mode and not set(mode) & set("cxru")
    if cmd == "xargs":   # reads if the command it runs does
        rest = args
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in {"-n", "-I", "-J", "-L", "-P", "-R", "-s", "-E"} else rest[1:]
        return not rest or segment_reads(rest)
    return cmd in SAFE_COMMANDS


def shell_needs(command: str) -> list[str] | None:
    """The commands in a shell line that need a rule: all but cd and read-only ones. None: unparseable."""
    segments = shell_segments(command)
    if segments is None:
        return None
    needs = [Path(s[0]).name for s in segments if Path(s[0]).name != "cd" and not segment_reads(s)]
    if BACKTICK.search(strip_heredocs(command)):
        needs.append("backticks")   # `...` hides a command from these checks ($(...) is split like any chain)
    return list(dict.fromkeys(needs))


def first_word(command: str) -> str:
    segments = shell_segments(command) or []
    names = [Path(s[0]).name for s in segments if Path(s[0]).name != "cd"]
    return names[0] if names else ("cd" if segments else "shell")


def shell_reads(command: str) -> bool:
    return shell_needs(command) == []


KILLERS = {"kill", "pkill", "killall"}
KILL_WORD = re.compile(r"\b(p?kill|killall)\b")
VALUE_OPTIONS = {"kill": {"-s", "-n"}, "pkill": {"-U", "-u", "-G", "-g", "-P", "-t", "-F", "-s", "-J"},
                 "killall": {"-u", "-t"}}   # their next word is a value, not a target


def stops_milo(command: str, procs: list[tuple[int, str, str]], markers: list[str]) -> bool:
    """A shell line that kills a process Milo runs in (the bridge, goose, Claude): Milo would end mid-reply and
    stay down. procs: (pid, name, command line) of those processes. markers: words that name them in a pid
    lookup (server.py, :8765), for a kill whose target is $(...) or comes from xargs."""
    if not KILL_WORD.search(command):
        return False
    segments = shell_segments(command) or [command.split()]   # unparseable: judge the whole line
    for tokens in segments:
        if tokens and Path(tokens[0]).name == "xargs":   # lsof -ti :8765 | xargs kill
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[2:] if tokens[0] in {"-n", "-I", "-J", "-L", "-P", "-R", "-s", "-E"} else tokens[1:]
        cmd = Path(tokens[0]).name if tokens else ""
        if cmd not in KILLERS:
            continue
        targets, i = [], 1
        while i < len(tokens):
            if tokens[i] in VALUE_OPTIONS[cmd]:
                i += 1
            elif not tokens[i].startswith("-"):
                targets.append(tokens[i])
            i += 1
        if cmd == "kill":
            pids = {pid for pid, _, _ in procs}
            if any(t.isdigit() and int(t) in pids for t in targets) or any(t in {"$PPID", "${PPID}"} for t in targets):
                return True
            if (not targets or not all(t.isdigit() for t in targets)) and any(m in command for m in markers):
                return True
            continue
        for t in targets:   # pkill: a pattern for the name (-f: the command line); killall: a name
            try:
                hit = re.compile(t, re.I).search
            except re.error:
                hit = lambda s, t=t: t.lower() in s.lower()
            if any(hit(name) or hit(line) for _, name, line in procs):
                return True
    return False


class Permissions:
    def __init__(self, path: Path):
        self.store = JsonFile(path, {})
        self.store.data.setdefault("auto_read", True)
        self.store.data.setdefault("rules", {})
        self.store.data.setdefault("seen", {})

    @property
    def auto_read(self) -> bool:
        return bool(self.store.data["auto_read"])

    def set_auto_read(self, value: bool) -> None:
        self.store.data["auto_read"] = bool(value)
        self.store.save()

    def rule(self, key: str) -> str | None:
        return self.store.data["rules"].get(key)

    def set_rule(self, key: str, rule: str) -> None:
        if rule not in RULES:
            raise ValueError("rule must be allow, deny or ask")
        if rule == "allow" and key_sends_email(key):
            raise ValueError("Sending email always asks")
        if rule == "ask":
            self.store.data["rules"].pop(key, None)
        else:
            self.store.data["rules"][key] = rule
        self.store.save()

    def reset_rules(self) -> None:
        self.store.data["rules"] = {}
        self.store.save()

    def seen(self, info: dict) -> None:
        keys = info.get("keys") or [info["key"]]
        for key in keys:
            entry = self.store.data["seen"].setdefault(key, {"count": 0})
            label = info["label"] if len(keys) == 1 else f"Shell: {key.split(':', 1)[1]}"
            entry.update(label=label, server=info["server"], read_only=info["read_only"], last=time.time())
            entry["count"] += 1
        self.store.save()

    def decide(self, info: dict, mode: str) -> str:
        """'allow', 'deny' or 'ask' for one request. 'Always ask' mode still honors deny rules."""
        rules = [self.rule(k) for k in info.get("keys") or [info["key"]]]
        if "deny" in rules:
            return "deny"
        if mode == "approve" or info.get("always_ask"):
            return "ask"
        if all(r == "allow" for r in rules):
            return "allow"
        return "allow" if self.auto_read and info["read_only"] else "ask"

    def listing(self) -> list[dict]:
        rows = []
        keys = set(self.store.data["seen"]) | set(self.store.data["rules"])
        for key in keys:
            s = self.store.data["seen"].get(key, {})
            rows.append({"key": key, "label": s.get("label", key.split(":")[-1]), "server": s.get("server", ""),
                         "read_only": s.get("read_only", False), "last": s.get("last"), "count": s.get("count", 0),
                         "rule": self.rule(key) or "ask"})
        return sorted(rows, key=lambda r: (r["server"].lower(), r["label"]))
