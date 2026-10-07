"""Private watchdog: no requests, credentials, or source content are inherited."""
import math
import os
import select
import signal
import sys
import time


def main():
    group, deadline = int(sys.argv[1]), float(sys.argv[2])
    if group <= 1 or not math.isfinite(deadline):
        return 2
    os.write(sys.stdout.fileno(), b"R")
    os.close(sys.stdout.fileno())
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([sys.stdin.fileno()], [], [], min(.1, remaining))
        if ready:
            message = os.read(sys.stdin.fileno(), 1)
            if message == b"D":  # owner already cleaned up
                return 0
            if not message:  # owner died or abandoned transport
                break
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
