import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent.parent / "packages" / "imprint_starlog" / "starlog.py"


def load(tmp: str):
    os.environ["STARLOG_DIR"] = tmp
    os.environ["STARLOG_DAY_START"] = "5"
    os.environ.pop("TZ_OFFSET", None)
    os.environ.pop("IMPRINT_STARLOG_CHILD", None)
    spec = importlib.util.spec_from_file_location("starlog", HERE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def transcript(path: Path, turns):
    with path.open("a") as f:
        for role, text, ts in turns:
            f.write(json.dumps({"type": role, "timestamp": ts,
                                "message": {"role": role, "content": [{"type": "text", "text": text}]}}) + "\n")


class StarlogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = load(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("STARLOG_DIR", None)

    def test_day_boundary(self):
        self.assertEqual(self.s.day_of(datetime(2026, 10, 21, 2, 0)), "2026-10-20")
        self.assertEqual(self.s.day_of(datetime(2026, 10, 21, 6, 0)), "2026-10-21")
        self.assertLess(self.s.clock_key(23, 0), self.s.clock_key(1, 30))

    def test_append_sorts_by_day_clock(self):
        self.s.append_line(datetime(2026, 10, 21, 1, 30), "telegram", "late one")
        self.s.append_line(datetime(2026, 10, 20, 23, 0), "cc·x", "earlier one")
        lines = self.s.read_lines("2026-10-20")
        self.assertEqual([l.split("] ")[1] for l in lines], ["earlier one", "late one"])

    def test_record_threshold_window_and_child_guard(self):
        tp = Path(self.tmp.name) / "t.jsonl"
        transcript(tp, [("user", '<channel source="plugin:telegram:telegram" chat_id="1">hi</channel>', "2026-10-20T09:00:00Z")])
        with mock.patch.object(self.s, "ask_model", return_value="I said hi.") as m:
            self.assertIsNone(self.s.record(str(tp), "sess1", "/x/proj"))   # too short
            m.assert_not_called()
            transcript(tp, [("assistant", "x" * 500, "2026-10-20T09:01:00Z")])
            line = self.s.record(str(tp), "sess1", "/x/proj")
            self.assertIn("[telegram] I said hi.", line)
            transcript(tp, [("user", "y" * 500, "2026-10-20T09:02:00Z")])
            self.assertIsNone(self.s.record(str(tp), "sess1", "/x/proj"))   # min interval
            os.environ["IMPRINT_STARLOG_CHILD"] = "1"
            try:
                self.assertIsNone(self.s.record(str(tp), "sess2", "/x/proj"))
            finally:
                os.environ.pop("IMPRINT_STARLOG_CHILD")

    def test_cc_window_name(self):
        tp = Path(self.tmp.name) / "c.jsonl"
        transcript(tp, [("user", "z" * 500, "2026-10-20T09:00:00Z")])
        with mock.patch.object(self.s, "ask_model", return_value="I worked."):
            self.assertIn("[cc·proj]", self.s.record(str(tp), "s", "/x/proj"))

    def _seed(self, n, start_h=10):
        for i in range(n):
            self.s.append_line(datetime(2026, 10, 20, start_h, i * 5), "telegram" if i % 2 else "cc·a", f"note {i}")

    def test_arrange_groups_and_loose(self):
        self._seed(4)
        fake = lambda p: "[NEW 1,2] We fixed it together.\n[NEW 3] Then I drew.\n"
        n = self.s.arrange("2026-10-20", force=True, model=fake)
        self.assertEqual(n, 4)
        st = self.s.load_state("2026-10-20")
        self.assertEqual([s["text"] for s in st["segments"]], ["We fixed it together.", "Then I drew."])
        self.assertEqual(sum(len(s["keys"]) for s in st["segments"]), 4)   # note 4 counted, not lost
        self.assertEqual(self.s.loose_lines("2026-10-20"), [])

    def test_arrange_revises_previous_and_falls_back_raw(self):
        self._seed(2)
        self.s.arrange("2026-10-20", force=True, model=lambda p: "[NEW 1,2] First thing.")
        self.s.append_line(datetime(2026, 10, 20, 10, 20), "telegram", "it continued")
        seen = {}
        def fake(p):
            seen["prompt"] = p
            return "[PREVIOUS] First thing, and it continued."
        self.s.arrange("2026-10-20", force=True, model=fake)
        self.assertIn("First thing.", seen["prompt"])
        st = self.s.load_state("2026-10-20")
        self.assertEqual(len(st["segments"]), 1)
        self.assertEqual(st["segments"][0]["text"], "First thing, and it continued.")
        self.assertEqual(st["segments"][0]["end"], "10:20")
        self.s.append_line(datetime(2026, 10, 20, 15, 0), "cc·a", "much later")
        self.s.arrange("2026-10-20", force=True, model=lambda p: None)
        st = self.s.load_state("2026-10-20")
        self.assertTrue(st["segments"][-1].get("raw"))
        self.assertIn("much later", st["segments"][-1]["text"])

    def test_arrange_waits_for_more_lines_today(self):
        now = self.s.now()
        self.s.append_line(now, "telegram", "just now")
        called = []
        self.s.arrange(None, model=lambda p: called.append(p) or "[NEW 1] x")
        self.assertEqual(called, [])

    def test_context_budget_and_since(self):
        now = self.s.now()
        today = self.s.day_of(now)
        for i in range(30):
            self.s.append_line(now.replace(hour=(now.hour - 1) % 24 if now.hour != self.s.DAY_START else now.hour, minute=i),
                               "cc·a" if i % 3 else "telegram", "w" * 200 + str(i))
        ctx = self.s.render_context(budget=2000)
        self.assertIn(f'<starlog day="{today}">', ctx)
        self.assertLessEqual(len(ctx), 2600)
        first = self.s.lines_since("hb", exclude_window="telegram")
        self.assertTrue(first and all("[telegram]" not in l for l in first))
        self.assertEqual(self.s.lines_since("hb", exclude_window="telegram"), [])


if __name__ == "__main__":
    unittest.main()
