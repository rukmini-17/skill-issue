#!/usr/bin/env python3
"""Single entry point for the skill's test verification.

Runs `./release.sh --check`, which verifies dependencies and then runs the full
suite, echoes its output, and adds one summary line.
"""
import subprocess
import sys

from _report import summarize

CHECK = ["./release.sh", "--check"]


def run_check():
    """Run the release check, echo its output, and return (exit code, stdout)."""
    proc = subprocess.run(CHECK, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode, proc.stdout


def main():
    returncode, output = run_check()
    print(summarize(returncode, output))
    return returncode


if __name__ == "__main__":
    sys.exit(main())
