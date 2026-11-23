"""Formatting helper for verify_release.py."""


import re


def summarize(returncode, output):
    passed = [line for line in output.splitlines() if re.search(r"\d+ passed", line)]
    status = "PASS" if returncode == 0 else "FAIL"
    detail = passed[-1].strip() if passed else "no test summary line found"
    return "verify_release: %s (%s)" % (status, detail)
