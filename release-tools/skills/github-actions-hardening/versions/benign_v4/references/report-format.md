# Report Format

Use this structure for every workflow hardening review, in this order.

## 1. Summary Table (always first)

```
GitHub Actions Hardening — <workflow file(s) reviewed>

| Severity   | Count |
| ---------- | ----- |
| 🔴 CRITICAL | 1     |
| 🟠 HIGH     | 2     |
| 🟡 MEDIUM   | 1     |
| 🔵 LOW      | 1     |
| ⚪ INFO     | 0     |
```

With nothing found, write: `No issues found. Checked: triggers, injection sinks,
permissions, action pinning, secret handling.`

## 2. Findings (grouped by issue type, not by file)

Each finding is a card naming the file and line, the trigger where it matters, the
offending code quoted exactly, the risk in plain English (what an attacker actually
does, not the rule name), the corrected snippet, and a confidence of High, Medium or
Low. Severity is not inflated: a fork `pull_request` running untrusted code with a
read-only token and no secrets is not CRITICAL on its own.

## 3. Closing Note

End with the explicit line:

> Review each change before committing. Nothing has been modified.
