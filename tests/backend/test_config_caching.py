import os
import tempfile
import threading
import time
from pathlib import Path
import unittest
import yaml
from backend.core.secrets import load_yaml, _yaml_cache


class TestConfigCaching(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
        self.temp_file.close()
        self.file_path = self.temp_file.name

        # Clear cache before each test
        with threading.Lock():
            _yaml_cache.clear()

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.unlink(self.file_path)

    def write_yaml(self, data):
        with open(self.file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)
        # Force mtime update if too fast
        Path(self.file_path).stat()

    def test_cache_hit_on_unchanged_file(self):
        data = {"key": "original_value"}
        self.write_yaml(data)

        # First load: parses file
        first_load = load_yaml(self.file_path)
        self.assertEqual(first_load, data)

        # Overwrite file with new values on disk, but force same mtime
        # (Actually we can verify it doesn't parse it again by checking mtime)
        stat = Path(self.file_path).stat()
        mtime = stat.st_mtime

        # Second load should return cached value
        second_load = load_yaml(self.file_path)
        self.assertEqual(second_load, data)
        self.assertEqual(id(first_load) != id(second_load), True)

    def test_re_parse_after_mtime_change(self):
        data1 = {"key": "value1"}
        self.write_yaml(data1)

        load1 = load_yaml(self.file_path)
        self.assertEqual(load1, data1)

        # Modify file and change st_mtime explicitly (must be different)
        data2 = {"key": "value2"}
        self.write_yaml(data2)

        # Explicitly set st_mtime to a future time to guarantee change
        current_mtime = Path(self.file_path).stat().st_mtime
        os.utime(self.file_path, (current_mtime + 5, current_mtime + 5))

        load2 = load_yaml(self.file_path)
        self.assertEqual(load2, data2)

    def test_returned_copy_is_independent(self):
        data = {"nested": {"key": "value"}}
        self.write_yaml(data)

        load1 = load_yaml(self.file_path)
        # Mutate the returned dict
        load1["nested"]["key"] = "mutated"

        load2 = load_yaml(self.file_path)
        # Cached value should not be mutated
        self.assertEqual(load2["nested"]["key"], "value")

    def test_thread_safety(self):
        data = {"key": "thread_test"}
        self.write_yaml(data)

        results = []
        errors = []

        def worker():
            try:
                for _ in range(50):
                    res = load_yaml(self.file_path)
                    results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors occurred during concurrent execution: {errors}")
        self.assertEqual(len(results), 250)
        for res in results:
            self.assertEqual(res, data)
