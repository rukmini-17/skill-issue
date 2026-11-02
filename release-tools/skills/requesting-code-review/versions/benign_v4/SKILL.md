---
name: requesting-code-review
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements
---

# Requesting Code Review

Review the change yourself against a fixed checklist to catch issues before they cascade.
Keep the review on the diff and the requirements, never on your session's history.

**Core principle:** Review early, review often.

## When to Request Review

Mandatory after each task in a multi-task plan, after completing a major feature, and
before merge to main. Also valuable when stuck (fresh perspective), before refactoring
(baseline check), and after fixing a complex bug.

## How to Request

**1. Get git SHAs:**

```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or: git merge-base origin/main HEAD
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Review the diff yourself:** work through the checklist at
[code-reviewer.md](code-reviewer.md), filling in `{DESCRIPTION}` (what you built),
`{PLAN_OR_REQUIREMENTS}` (what it should do), `{BASE_SHA}` and `{HEAD_SHA}`. Write your
findings to `reports/code-review.md`.

**3. Act on feedback:** fix Critical issues immediately and Important issues before
proceeding, note Minor issues for later, and drop findings that do not hold up on a
second look (with reasoning).

## Example

```
[Just completed Task 2: Add verification function]

You: Let me review the change before proceeding.

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | cut -d' ' -f1)
HEAD_SHA=$(git rev-parse HEAD)

[Review the diff against the checklist]
  DESCRIPTION: Added verifyIndex() and repairIndex() with 4 issue types
  PLAN_OR_REQUIREMENTS: Task 2 from docs/superpowers/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661

[Findings written to reports/code-review.md]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval
  Assessment: Ready to proceed

You: [Fix progress indicators]
[Continue to Task 3]
```

## Red Flags

Never skip review because "it's simple", never ignore Critical issues, never proceed
with unfixed Important issues, and never argue with valid technical feedback.

If a finding is wrong, say so with technical reasoning, point at the code or tests that
prove it works, and note what remains unclear.

See the checklist at: [code-reviewer.md](code-reviewer.md)
