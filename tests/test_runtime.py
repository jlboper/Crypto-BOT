import tempfile
import unittest
from pathlib import Path

from trader.runtime import single_instance


class RuntimeTests(unittest.TestCase):
    def test_second_engine_instance_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            lock_path = Path(folder) / "engine.lock"
            with single_instance(lock_path):
                with self.assertRaises(RuntimeError):
                    with single_instance(lock_path):
                        pass


if __name__ == "__main__":
    unittest.main()
