"""Local guard exclusivity, exception release, and actual process-death release."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from league_knowledge_platform import RunBusyError
from league_knowledge_platform.run_lock import execution_guard
from run_fixtures import process_environment


class RunLockTests(unittest.TestCase):
    def test_exception_releases_guard_without_deleting_its_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "injected"):
                with execution_guard(path):
                    with self.assertRaises(RunBusyError):
                        with execution_guard(path):
                            self.fail("Reentrant guard acquired")
                    raise RuntimeError("injected")
            with execution_guard(path):
                self.assertTrue(path.with_name(path.name + ".lock").exists())

    def test_other_process_cannot_acquire_and_killed_process_releases_os_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            code = """
import sys
from pathlib import Path
from league_knowledge_platform.run_lock import execution_guard
with execution_guard(Path(sys.argv[1])):
    print('LOCKED', flush=True)
    sys.stdin.read()
"""
            process = subprocess.Popen([sys.executable, "-B", "-c", code, str(path)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, env=process_environment())
            try:
                self.assertEqual(process.stdout.readline().strip(), "LOCKED")
                with self.assertRaises(RunBusyError):
                    with execution_guard(path):
                        self.fail("Concurrent guard acquired")
                process.kill()
                process.communicate(timeout=15)
                with execution_guard(path):
                    pass
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=15)


if __name__ == "__main__":
    unittest.main()
