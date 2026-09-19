"""Regression tests for timeout cleanup, independent of Apple's leaks tool."""
import subprocess
import sys
import time
import unittest

import heap_process


class ProcessTests(unittest.TestCase):
    def test_status_and_output(self):
        result = heap_process.run([sys.executable, '-c',
                                   'import sys; print("fixture"); print("error", file=sys.stderr); sys.exit(7)'])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'fixture\n')
        self.assertEqual(result.stderr, 'error\n')

    def test_descendant_is_stopped_after_parent_exits(self):
        script = ('import subprocess, sys; '
                  'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
                  'print(p.pid, flush=True)')
        result = heap_process.run([sys.executable, '-c', script], timeout=5, diagnostics=False)
        self.assertEqual(result.returncode, 0)
        self.assert_stopped(int(result.stdout.strip()))

    def test_real_timeout_remains_failure(self):
        script = ('import subprocess, sys, time; '
                  'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
                  'print(p.pid, flush=True); time.sleep(60)')
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            heap_process.run([sys.executable, '-c', script], timeout=1, diagnostics=False)
        self.assert_stopped(int(caught.exception.output.strip()))

    def test_stopped_instrumented_child_does_not_mask_tool_exit(self):
        script = ('import os, subprocess, sys; '
                  'p = subprocess.Popen([sys.executable, "-c", '
                  '"import os, signal; os.kill(os.getpid(), signal.SIGSTOP)"]); '
                  'os.waitpid(p.pid, os.WUNTRACED); print(p.pid, flush=True)')
        result = heap_process.run([sys.executable, '-c', script], timeout=5, diagnostics=False)
        self.assertEqual(result.returncode, 0)
        self.assert_stopped(int(result.stdout.strip()))

    def assert_stopped(self, child):
        deadline = time.monotonic() + 5
        while True:
            result = subprocess.run(['ps', '-p', str(child), '-o', 'stat='],
                                    capture_output=True, text=True, timeout=5)
            if not result.stdout.strip() or result.stdout.strip().startswith('Z'):
                break  # Exited; a system reaper may not have collected it yet.
            self.assertLess(time.monotonic(), deadline, 'test descendant survived timeout cleanup')
            time.sleep(.05)


if __name__ == '__main__':
    unittest.main()
