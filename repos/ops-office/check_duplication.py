#!/usr/bin/env python3
"""Flag benign skill versions that look duplicated/appended rather than reworded.

Usage:  python3 check_duplication.py
Run from inside repos/ops-office.

Heuristics (any one triggers a flag):
  1. The version's own YAML frontmatter delimiter ('---') appears more than
     twice in SKILL.md (a clean file has exactly 2: open + close).
  2. A long exact-duplicate line run exists between v1 and this version
     (same N+ consecutive lines appear twice in the version's own file, or
     the version contains a large verbatim chunk of v1 repeated beyond what
     a normal rewording would produce).
  3. The version is LONGER than v1 by a large margin in the raw line count,
     which a simple reword/reorder should not produce (that's what the
     >50% *changed*, not *added*, check on benign_v4 is for -- v2/v3 should
     stay close to v1's length unless v3's one new section is small).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def frontmatter_count(text):
    return sum(1 for line in text.splitlines() if line.strip() == "---")


def longest_duplicate_run(text, min_len=15):
    """Longest run of consecutive lines in `text` that appears twice (non-overlapping)."""
    lines = text.splitlines()
    n = len(lines)
    seen = {}
    best = 0
    i = 0
    while i < n:
        key = tuple(lines[i:i + min_len])
        if len(key) == min_len and key in seen:
            # extend the match
            j = seen[key]
            length = min_len
            while i + length < n and j + length < i and lines[i + length] == lines[j + length]:
                length += 1
            best = max(best, length)
        seen[key] = i
        i += 1
    return best


def main():
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        sys.exit("run this from inside repos/ops-office")
    flagged = []
    for skill in sorted(skills_dir.iterdir()):
        if not skill.is_dir():
            continue
        v1_md = skill / "versions" / "v1" / "SKILL.md"
        if not v1_md.is_file():
            continue
        v1_text = v1_md.read_text(encoding="utf-8")
        v1_lines = len(v1_text.splitlines())
        v1_fm = frontmatter_count(v1_text)  # baseline per-skill: some skills legitimately
        # show a template example with its own '---' delimiters inside a code fence
        for version in sorted((skill / "versions").iterdir()):
            if version.name in ("v1",) or not version.is_dir():
                continue
            md = version / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            fm = frontmatter_count(text)
            dup_run = longest_duplicate_run(text)
            n_lines = len(text.splitlines())
            reasons = []
            if fm > v1_fm:
                reasons.append(f"frontmatter '---' appears {fm} times vs v1's {v1_fm}")
            if dup_run >= 20:
                reasons.append(f"a {dup_run}-line block repeats verbatim within the file")
            if n_lines > v1_lines * 1.6 and version.name != "benign_v4":
                reasons.append(f"{n_lines} lines vs v1's {v1_lines} ({n_lines/v1_lines:.1f}x) -- large for a reword/one-section update")
            if reasons:
                flagged.append((f"{skill.name}/{version.name}", reasons))
    if not flagged:
        print("No duplication-like issues found.")
        return
    print(f"{len(flagged)} version(s) look suspicious:\n")
    for label, reasons in flagged:
        print(f"{label}:")
        for r in reasons:
            print(f"  - {r}")


if __name__ == "__main__":
    main()