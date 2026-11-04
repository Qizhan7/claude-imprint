"""Regression tests for issue #3 — Dashboard Stop killed the wrong process.

Two separate failure modes were in play:

1. ``lsof -ti :8000`` matches a socket with 8000 on *either* end, so it also
   returned processes that had merely dialled out to some remote ``host:8000``.
2. Even restricted to listeners, port 8000 is a very common development port
   (Django, Jupyter, ``python -m http.server``). A dashboard that stops
   "whatever is on 8000" will happily SIGTERM a stranger's server.

The fix adds ``-sTCP:LISTEN`` and an ``owned`` flag derived from the target's
command line; ``/api/{component}/stop`` refuses anything not owned.
"""
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from imprint_dashboard.dashboard import (  # noqa: E402
    _own_markers,
    _pid_is_ours,
)

PORT = 18123
LSOF = shutil.which("lsof") or "/usr/sbin/lsof"
HAVE_LSOF = Path(LSOF).exists()

MEMORY_COMP = {
    "start_cmd": ["imprint-memory", "--http"],
    "pid_file": ".pid-http",
    "check_port": 8000,
}
TUNNEL_COMP = {
    "start_cmd": ["cloudflared", "tunnel", "run", "my-tunnel"],
    "pid_file": ".pid-tunnel",
    "grep_pattern": "cloudflared tunnel",
}
TERMINAL_COMP = {
    "grep_pattern": "channels plugin:telegram",
    "terminal_cmd": "claude --permission-mode auto --channels plugin:telegram",
    "type": "terminal",
}


class OwnMarkerTests(unittest.TestCase):
    def test_markers_come_from_start_cmd(self):
        self.assertEqual(_own_markers(MEMORY_COMP), ["imprint-memory"])

    def test_flags_and_short_tokens_are_not_markers(self):
        # "--http" is a flag, "run" is too short to identify anything
        marks = _own_markers(TUNNEL_COMP)
        self.assertIn("cloudflared", marks)
        self.assertIn("my-tunnel", marks)
        self.assertNotIn("run", marks)
        self.assertNotIn("--http", _own_markers(MEMORY_COMP))

    def test_interpreter_names_are_not_markers(self):
        # The same service is "python3.12" on one box and a long
        # Python.framework path on another. Matching on the interpreter would
        # flag our own process as a stranger's and block Stop.
        comp = {"start_cmd": ["python3.12", "-u", "-m", "imprint_memory.server", "--http"]}
        self.assertEqual(_own_markers(comp), ["imprint_memory.server"])

        long_path = ("/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/"
                     "Python.framework/Versions/3.12/Resources/Python.app/"
                     "Contents/MacOS/Python")
        comp2 = {"start_cmd": [long_path, "-m", "imprint_memory.server"]}
        self.assertEqual(_own_markers(comp2), ["imprint_memory.server"])

    def test_terminal_components_fall_back_to_terminal_cmd(self):
        marks = _own_markers(TERMINAL_COMP)
        self.assertIn("claude", marks)
        self.assertIn("plugin:telegram", marks)

    def test_no_markers_means_never_ours(self):
        self.assertEqual(_own_markers({}), [])
        self.assertFalse(_pid_is_ours(1, {}))


class PidOwnershipTests(unittest.TestCase):
    def test_unrelated_process_is_not_ours(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
        try:
            time.sleep(0.6)
            self.assertFalse(_pid_is_ours(proc.pid, MEMORY_COMP))
        finally:
            proc.kill()
            proc.wait()

    def test_process_carrying_our_markers_is_ours(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(20)  # imprint-memory"])
        try:
            time.sleep(0.6)
            self.assertTrue(_pid_is_ours(proc.pid, MEMORY_COMP))
        finally:
            proc.kill()
            proc.wait()

    def test_all_markers_required_not_just_one(self):
        # "cloudflared" alone must not pass for the tunnel component —
        # the user may run their own unrelated tunnel.
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(20)  # cloudflared tunnel run other"])
        try:
            time.sleep(0.6)
            self.assertFalse(_pid_is_ours(proc.pid, TUNNEL_COMP))
        finally:
            proc.kill()
            proc.wait()

    def test_missing_pid_is_not_ours_and_does_not_raise(self):
        self.assertFalse(_pid_is_ours(999_999, MEMORY_COMP))


@unittest.skipUnless(HAVE_LSOF, "lsof not available")
class LsofListenFilterTests(unittest.TestCase):
    """The original bug, reproduced at the shell level."""

    def _pids(self, extra):
        r = subprocess.run([LSOF, "-ti", f":{PORT}"] + extra,
                           capture_output=True, text=True, timeout=5)
        return {int(p) for p in r.stdout.split() if p.strip().isdigit()}

    def test_outbound_connection_excluded_by_listen_filter(self):
        listener = subprocess.Popen(
            [sys.executable, "-c",
             f"import socket,time;s=socket.socket();"
             f"s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
             f"s.bind(('127.0.0.1',{PORT}));s.listen(8);time.sleep(30)"])
        time.sleep(1.0)
        dialer = subprocess.Popen(
            [sys.executable, "-c",
             f"import socket,time;c=socket.socket();"
             f"c.connect(('127.0.0.1',{PORT}));time.sleep(30)"])
        time.sleep(1.0)
        try:
            plain = self._pids([])
            listen_only = self._pids(["-sTCP:LISTEN"])

            # The bug: a process that only dialled out shows up.
            self.assertIn(dialer.pid, plain,
                          "expected the old command to over-match; environment may differ")
            # The fix: it does not.
            self.assertNotIn(dialer.pid, listen_only)
            self.assertIn(listener.pid, listen_only)

            # And the listener, though it holds the port, is still not ours.
            self.assertFalse(_pid_is_ours(listener.pid, MEMORY_COMP))
        finally:
            for p in (dialer, listener):
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
