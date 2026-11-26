"""COOK (or any machine) setup check: does the sandbox have what the tasks need?

    .venv/bin/python -m bench.harness.check_env [--isolation netns]

Builds a real sandbox (ops-office, with setup.sh and the v1 skills, the same code path
as a run) and runs the checks *inside it*, with the environment and PATH that agent
commands get. Fails loudly (exit 1, one line per problem, and the fix) when:

* `python` / `python3` inside the sandbox are not this venv's interpreter, or this
  interpreter is not a venv;
* a Python module that a skill script or a reference needs is missing (every skill
  version's requirements.txt in all four repos, plus bench/harness/requirements.txt);
* `pytest`, `ruff`, `git`, `node` or `npm` is not on the sandbox PATH;
* ops-office's skill script `convert_excel_to_md.py` does not convert
  `finance/expenses.xlsx` (the failure seen on COOK in pilot run ops-office-t01).

Prints versions and pin mismatches as warnings. Never prints file contents.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bench.harness.run import REPOS, make_mock
from bench.harness.sandbox import make_sandbox
from bench.harness.skills import repo_install_set

HERE = Path(__file__).resolve().parent
# distribution name -> import name, where they differ
IMPORT_NAME = {"pyyaml": "yaml", "pytest-cov": "pytest_cov", "markitdown": "markitdown"}
COMMANDS = ("python", "python3", "pytest", "ruff", "git", "node", "npm")


def requirement_lines() -> list[tuple[str, str, str]]:
    """(source, distribution, pin) from bench/harness/requirements.txt and every skill's."""
    files = [HERE / "requirements.txt", *sorted(REPOS.glob("*/skills/*/versions/*/requirements.txt")),
             *sorted(REPOS.glob("*/skills/*/versions/*/scripts/requirements.txt"))]
    out = []
    for f in files:
        for raw in f.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = re.match(r"([A-Za-z0-9_.-]+)(\[[^\]]*\])?\s*(.*)", line)
            if m:
                out.append((str(f.relative_to(REPOS.parent)), m.group(1).lower(), m.group(3).strip()))
    return out


PROBE = r'''
import importlib, importlib.metadata as md, json, sys
mods, dists = json.loads(sys.argv[1]), json.loads(sys.argv[2])
res = {"executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
       "version": sys.version.split()[0], "missing": [], "versions": {}}
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        res["missing"].append(f"{m}: {type(e).__name__}: {e}"[:200])
for d in dists:
    try:
        res["versions"][d] = md.version(d)
    except Exception:
        res["versions"][d] = None
print(json.dumps(res))
'''


def main(argv: list[str] | None = None) -> int:
    import json
    import shlex
    ap = argparse.ArgumentParser(prog="python -m bench.harness.check_env")
    ap.add_argument("--isolation", default="auto")
    a = ap.parse_args(argv)
    problems: list[str] = []
    warnings: list[str] = []
    if sys.prefix == sys.base_prefix:
        problems.append(f"the harness is not running from a venv ({sys.executable}); run it as .venv/bin/python")

    reqs = requirement_lines()
    dists = sorted({d for _, d, _ in reqs})
    mods = sorted({IMPORT_NAME.get(d, d.replace("-", "_")) for d in dists})

    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="cdb-check-env-"))
    mock, _ = make_mock("auto")
    proxy = mock.start("ops-office", tmp / "mock.jsonl")
    sb = make_sandbox(REPOS / "ops-office", proxy, isolation=a.isolation)
    try:
        sb.build(repo_install_set(REPOS / "ops-office"))
        print(f"sandbox: isolation {sb.isolation}, workspace {sb.workspace}")
        print(f"PATH inside: {sb.env()['PATH'].split(':')[:3]} ...")
        for c in COMMANDS:
            r = sb.run(f"command -v {c}")
            where = r.stdout.strip()
            print(f"  {c:8s} -> {where or 'NOT FOUND'}")
            if r.exit != 0 or not where:
                problems.append(f"`{c}` is not on the sandbox PATH")
        for c, flag in (("node", "--version"), ("npm", "--version"), ("git", "--version"), ("ruff", "--version"),
                        ("pytest", "--version")):
            r = sb.run(f"{c} {flag}")
            print(f"  {c} {flag}: exit {r.exit} {(r.stdout or r.stderr).strip().splitlines()[:1]}")
            if r.exit != 0:
                problems.append(f"`{c} {flag}` fails inside the sandbox (exit {r.exit})")
        for py in ("python", "python3"):
            r = sb.run(f"{py} -c {shlex.quote(PROBE)} {shlex.quote(json.dumps(mods))} {shlex.quote(json.dumps(dists))}")
            if r.exit != 0:
                problems.append(f"`{py}` inside the sandbox does not run (exit {r.exit}): {r.stderr.strip()[-300:]}")
                continue
            info = json.loads(r.stdout.strip().splitlines()[-1])
            print(f"  {py}: {info['executable']} (Python {info['version']}, prefix {info['prefix']})")
            if Path(info["prefix"]).resolve() != Path(sys.prefix).resolve():
                problems.append(f"`{py}` inside the sandbox is {info['executable']} (prefix {info['prefix']}), "
                                f"not this venv ({sys.prefix})")
            for miss in info["missing"]:
                problems.append(f"`{py}` cannot import {miss}")
            if py == "python3":
                for src, d, pin in reqs:
                    have = info["versions"].get(d)
                    if pin.startswith("==") and have and have != pin[2:]:
                        warnings.append(f"{d} {have} installed; {src} pins {pin}")
                print("  versions: " + ", ".join(f"{d} {v}" for d, v in sorted(info["versions"].items())))
        r = sb.run("python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance/expenses.xlsx"
                   " > /dev/null")
        print(f"  convert_excel_to_md.py finance/expenses.xlsx: exit {r.exit}")
        if r.exit != 0:
            problems.append("the convert-excel-to-md skill script fails inside the sandbox: "
                            + " | ".join(r.stderr.strip().splitlines()[-3:])[:400])
    finally:
        sb.close()
        mock.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    for w in warnings:
        print(f"WARNING: {w}")
    if problems:
        print(f"\nENVIRONMENT CHECK FAILED ({len(problems)} problems):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nFix: .venv/bin/pip install -r bench/harness/requirements.txt (and load the partition's "
              "modules for node/npm/git), then run this check again.", file=sys.stderr)
        return 1
    print("\nenvironment OK: the sandbox's python/python3 are this venv's and every requirement is present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
