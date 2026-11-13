"""Rendering helpers for Keep a Changelog sections."""

SECTIONS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

TYPE_TO_SECTION = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "docs": "Changed",
    "build": "Changed",
    "ci": "Changed",
    "revert": "Removed",
}


def split_entries(messages):
    """Group Conventional Commit subjects into Keep a Changelog sections."""
    grouped = {}
    for message in messages:
        subject = message.strip().splitlines()[0] if message.strip() else ""
        if not subject or ":" not in subject:
            continue
        head, text = subject.split(":", 1)
        kind = head.split("(", 1)[0].rstrip("!").strip().lower()
        section = TYPE_TO_SECTION.get(kind)
        if section is None:
            continue
        grouped.setdefault(section, []).append(text.strip())
    return grouped


def render_section(version, date, grouped):
    """Render one released version block in Keep a Changelog order."""
    lines = ["## [%s] - %s" % (version, date), ""]
    for name in SECTIONS:
        items = grouped.get(name)
        if not items:
            continue
        lines.append("### %s" % name)
        lines.append("")
        for item in items:
            lines.append("- %s" % item)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
