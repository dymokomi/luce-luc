"""Bounded POSIX test subprocesses; diagnose and kill only our own process group."""
import os
import signal
import subprocess
import sys
import tempfile


def diagnose(group):
    """No unrelated command lines or environment variables are logged."""
    try:
        result = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid=,stat=,comm='],
                                capture_output=True, text=True, timeout=5, check=True)
        members = []
        for row in result.stdout.splitlines():
            fields = row.split(None, 4)
            if len(fields) == 5 and int(fields[2]) == group:
                print('TIMED-OUT TEST PROCESS:', row, file=sys.stderr, flush=True)
                members.append(int(fields[0]))
        if sys.platform == 'darwin':
            for pid in members[:4]:
                # Sampling failure must never prevent cleanup of the test group.
                sample = subprocess.run(['/usr/bin/sample', str(pid), '1', '1'],
                                        capture_output=True, text=True, timeout=5)
                print(sample.stdout, file=sys.stderr, flush=True)
                print(sample.stderr, file=sys.stderr, flush=True)
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        print('Test timeout diagnostics failed:', failure, file=sys.stderr, flush=True)


def run(command, *, env=None, cwd=None, timeout=120, diagnostics=True):
    """Wait for actual tool exit, not EOF on pipes held by instrumented children.

    macOS 15 leaks can finish its report and leave its child stopped in
    libLeaksAtExit. Regular-file capture avoids mistaking that inherited pipe
    for a still-running tool. Reap the tool and clean up its own group on every
    outcome; callers still verify tool status, fixture completion and leak report.
    """
    command = list(map(str, command))
    with tempfile.TemporaryFile(mode='w+') as output, tempfile.TemporaryFile(mode='w+') as errors:
        with subprocess.Popen(command, env=env, cwd=cwd, stdout=output, stderr=errors,
                              start_new_session=True) as process:
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if diagnostics: diagnose(process.pid)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read(), errors.read()
            if timed_out:
                print(stdout, end='', flush=True)
                print(stderr, end='', file=sys.stderr, flush=True)
                raise subprocess.TimeoutExpired(command, timeout, stdout, stderr) from None
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
