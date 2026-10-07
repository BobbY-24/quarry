"""Reviewed stdlib bootstrap establishes an owner watchdog before adapter exec.

Arguments contain only operator-reviewed command argv, a descriptor and a local
deadline. Requests arrive separately on stdin. The guardian gets no credentials.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    # Bound the tiny startup interval even if the owner dies before the guardian
    # exists. Signals persist as pending timers across exec until disabled below.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, 2)
    owner_fd, deadline = int(sys.argv[1]), float(sys.argv[2])
    command = json.loads(sys.argv[3])
    if owner_fd <= 2 or not math.isfinite(deadline) or deadline <= time.monotonic():
        return 2
    env = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    guardian = subprocess.Popen([sys.executable, "-m", "termfinder.process_guardian", str(os.getpgrp()), str(deadline)],
                                stdin=owner_fd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, close_fds=True, start_new_session=True)
    os.close(owner_fd)
    if guardian.stdout.read(1) != b"R":
        return 2
    guardian.stdout.close()
    # The watchdog now owns the owner's read pipe. It kills this process group
    # on EOF or deadline regardless of adapter signal handlers.
    signal.setitimer(signal.ITIMER_REAL, 0)
    os.execve(command[0], command, os.environ)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
