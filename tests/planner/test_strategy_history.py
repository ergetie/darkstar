import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.strategy.history import append_strategy_event, get_strategy_history


class TestStrategyHistory(unittest.TestCase):
    def setUp(self):
        # Point the history file at a throwaway dir so the real data/ is never touched
        # and parallel workers cannot collide.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch(
            "backend.strategy.history.HISTORY_FILE",
            Path(tmp.name) / "strategy_history.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_append_and_retrieve(self):
        append_strategy_event("TEST_EVENT", "This is a test", {"foo": "bar"})

        history = get_strategy_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["type"], "TEST_EVENT")
        self.assertEqual(history[0]["message"], "This is a test")
        self.assertEqual(history[0]["details"]["foo"], "bar")

    def test_limit(self):
        for i in range(110):
            append_strategy_event(f"EVENT_{i}", f"Message {i}")

        history = get_strategy_history(limit=100)
        self.assertEqual(len(history), 100)
        self.assertEqual(history[0]["type"], "EVENT_109")


if __name__ == "__main__":
    unittest.main()
