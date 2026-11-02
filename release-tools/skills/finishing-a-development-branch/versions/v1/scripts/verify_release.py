#!/usr/bin/env python3
"""Run the project's release check and print a one-line summary.

Wraps `./release.sh --check` (dependency check plus the full test suite) so the
skill has a single command for Step 1.
"""
import subprocess
import sys

from _report import summarize


def main():
    proc = subprocess.run(["./release.sh", "--check"], capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    print(summarize(proc.returncode, proc.stdout))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
