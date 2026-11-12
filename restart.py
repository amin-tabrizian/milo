"""Starts the Milo bridge again once the old one has exited. server.py runs it, detached, for Milo's <restart/>:
Milo runs inside the bridge, so it can't restart it with a shell command."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
LOG = Path.home() / "Library" / "Logs" / "milo.log"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # exited but not yet reaped by its parent (a zombie) counts as gone
    return not subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.startswith("Z")


def main() -> None:
    old, start, again = int(sys.argv[1]), time.time(), False
    while alive(old):
        waited = time.time() - start
        if waited > 60:   # stuck in shutdown: the new bridge needs the port
            os.kill(old, signal.SIGKILL)
        elif waited > 20 and not again:   # a second signal makes uvicorn stop waiting for open requests
            os.kill(old, signal.SIGTERM)
            again = True
        time.sleep(0.2)
    if os.isatty(1):   # started from a Terminal window that may close: log to the file like a detached bridge
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(ROOT / "server.py")])


if __name__ == "__main__":
    main()
