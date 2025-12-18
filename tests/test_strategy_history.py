import unittest
import os
import json
import shutil
from backend.strategy.history import append_strategy_event, get_strategy_history, HISTORY_FILE


class TestStrategyHistory(unittest.TestCase):
    def setUp(self):
        # Backup existing history if any
        if os.path.exists(HISTORY_FILE):
            shutil.move(HISTORY_FILE, HISTORY_FILE + ".bak")

    def tearDown(self):
        # Restore backup
        if os.path.exists(HISTORY_FILE + ".bak"):
            shutil.move(HISTORY_FILE + ".bak", HISTORY_FILE)
        elif os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)

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
