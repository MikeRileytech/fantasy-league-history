import contextlib
import importlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import season_refresh


class StartTests(unittest.TestCase):
    """app.py calls start() on every run; there is only ever one check."""

    def start(self, running=()):
        started = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                self.args = (target, name, daemon)

            def start(self):
                started.append(self.args)

        threads = [SimpleNamespace(name=name) for name in running]
        with patch.object(season_refresh, "PROJECT_DIR", Path("/mount/src/fantasy-league-history")), \
                patch("threading.Thread", FakeThread), \
                patch("threading.enumerate", lambda: threads):
            season_refresh.start()
        return started

    def test_starts_one_named_check_on_streamlit_cloud(self):
        self.assertEqual(self.start(running=["MainThread"]),
                         [(season_refresh._run_forever, "season_refresh", True)])

    def test_never_a_second_check(self):
        self.assertEqual(self.start(running=["MainThread", "season_refresh"]), [])

    def test_a_check_started_before_threads_were_named_counts(self):
        self.assertEqual(self.start(running=["Thread-3 (_run_forever)"]), [])

    def test_nothing_runs_locally(self):
        with patch("threading.Thread") as thread:
            season_refresh.start()  # this checkout isn't under /mount/src
        thread.assert_not_called()


class ReloadTests(unittest.TestCase):
    """Deploys reach the check by reloading or re-importing this module."""

    def test_reloading_keeps_what_was_committed(self):
        pushed, ranked, lock = season_refresh._pushed, season_refresh._ranked, season_refresh._lock
        pushed.add((2026, 6, 6))
        self.addCleanup(pushed.discard, (2026, 6, 6))
        module = importlib.reload(season_refresh)
        self.assertIs(module._pushed, pushed)
        self.assertIs(module._ranked, ranked)
        self.assertIs(module._lock, lock)
        self.assertIn((2026, 6, 6), module._pushed)

    def test_the_running_check_uses_the_newest_copy(self):
        # Streamlit re-imports a changed module as a new copy; the thread the
        # old copy started must run the new copy's code.
        calls = []
        newest = SimpleNamespace(refresh_once=lambda: calls.append("newest") or "done")

        class Stop(Exception):
            pass

        def stop(seconds):
            raise Stop

        with patch.dict(sys.modules, {"season_refresh": newest}), \
                patch("time.sleep", stop), contextlib.redirect_stdout(io.StringIO()) as out, \
                self.assertRaises(Stop):
            season_refresh._run_forever()
        self.assertEqual(calls, ["newest"])
        self.assertIn("[season_refresh] done", out.getvalue())


if __name__ == "__main__":
    unittest.main()
