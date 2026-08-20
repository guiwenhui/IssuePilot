import os
import signal
import subprocess
import sys


MAX_HARD_TIMEOUT_SECONDS = 610


def main() -> int:
    configured = int(os.environ.get("ISSUEPILOT_HARD_TIMEOUT_SECONDS", "130"))
    timeout = max(1, min(configured, MAX_HARD_TIMEOUT_SECONDS))
    process = subprocess.Popen(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        print("pytest runner hard timeout exceeded", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
