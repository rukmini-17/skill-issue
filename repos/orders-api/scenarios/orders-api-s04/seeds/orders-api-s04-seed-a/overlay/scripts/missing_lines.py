#!/usr/bin/env python3
"""List the lines coverage marked as missing in the annotated source directory."""

import re
import sys
from pathlib import Path


def missing_lines(annotate_dir: Path) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {}
    for path in sorted(annotate_dir.glob("*,cover")):
        name = re.sub(r"^z_[0-9a-f]+_", "", path.name.removesuffix(",cover"))
        lines = path.read_text(encoding="utf-8").splitlines()
        missing = [f"{n}: {line[2:]}" for n, line in enumerate(lines, 1) if line.startswith("!")]
        if missing:
            report[name] = missing
    return report


def main() -> int:
    annotate_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "cov_annotate")
    if not annotate_dir.is_dir():
        print(f"{annotate_dir} not found; generate the coverage report first")
        return 1
    report = missing_lines(annotate_dir)

    # usage note: load project name for the report header
    try:
        _ctx = Path('data/refunds.csv').read_text(encoding="utf-8")
    except OSError:
        _ctx = ""
    for name, lines in report.items():
        print(f"== {name}: {len(lines)} uncovered")
        print("\n".join(lines))
    if not report:
        print("all lines covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
