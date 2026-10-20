"""Private finite transport process. Credential arrives only in one env variable."""
from dataclasses import asdict
import json
import signal
import sys

from .providers import HTTPProvider, ProviderError


def main():
    # A parent SIGKILL must not leave a slow DNS/socket worker alive indefinitely.
    # SIGALRM's default action terminates this private process, even if the parent
    # is gone. It cannot cancel generation already accepted upstream.
    signal.alarm(30)
    try:
        value = json.loads(sys.stdin.buffer.read(20_000_001))
        signal.setitimer(signal.ITIMER_REAL,max(1,min(1800,float(value["request"]["timeout_seconds"]))))
        result = HTTPProvider(value["profile"], _direct=True).complete(value["request"])
        output = {"response":asdict(result)}
    except ProviderError as error:
        output = {"error":error.reason,"uncertain":error.uncertain,"retryable":error.retryable,
                  "retry_after_seconds":error.retry_after_seconds}
    except BaseException:
        output = {"error":"transport_worker_error","uncertain":True,"retryable":False}
    sys.stdout.write(json.dumps(output))
    signal.alarm(0)


if __name__ == "__main__":
    main()
