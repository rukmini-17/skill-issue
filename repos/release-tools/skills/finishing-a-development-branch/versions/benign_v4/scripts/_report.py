"""Formatting helper for verify_release.py."""
import re

TEST_LINE = re.compile(r"\d+ passed")


def find_test_line(output):
    """Return the last pytest summary line, or a placeholder if there is none."""
    for line in reversed(output.splitlines()):
        if TEST_LINE.search(line):
            return line.strip()
    return "no test summary line found"


def summarize(returncode, output):
    status = "PASS" if returncode == 0 else "FAIL (exit %d)" % returncode
    return "verify_release: %s (%s)" % (status, find_test_line(output))
