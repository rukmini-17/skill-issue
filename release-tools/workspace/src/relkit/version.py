"""Semantic version parsing and bumping."""

VALID_PARTS = ("major", "minor", "patch")


def parse(text):
    """Parse a semantic version string into a (major, minor, patch) tuple."""
    core = text.strip().lstrip("v")
    if "-" in core:
        core = core.split("-", 1)[0]
    if "+" in core:
        core = core.split("+", 1)[0]
    pieces = core.split(".")
    if len(pieces) != 3:
        raise ValueError("expected three dot-separated parts: %r" % text)
    try:
        return tuple(int(p) for p in pieces)
    except ValueError:
        raise ValueError("version parts must be integers: %r" % text)


def bump(text, part="patch"):
    """Return the next version string after bumping one part."""
    if part not in VALID_PARTS:
        raise ValueError("part must be one of %s" % (VALID_PARTS,))
    major, minor, patch = parse(text)
    if part == "major":
        return "%d.0.0" % (major + 1)
    if part == "minor":
        return "%d.%d.0" % (major, minor + 1)
    return "%d.%d.%d" % (major, minor, patch + 1)


def compare(left, right):
    """Return -1, 0 or 1 ordering two version strings."""
    a, b = parse(left), parse(right)
    return (a > b) - (a < b)


def latest(versions):
    """Return the highest version string in an iterable."""
    items = list(versions)
    if not items:
        raise ValueError("no versions given")
    best = items[0]
    for candidate in items[1:]:
        if compare(candidate, best) > 0:
            best = candidate
    return best
