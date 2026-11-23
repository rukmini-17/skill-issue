---
name: requesting-code-review
description: Use before merging, or after finishing a task or feature, to check the work against its requirements
---

# Requesting Code Review

You are the reviewer here. Check the change against a fixed checklist so problems are
caught before later work builds on them. Judge the diff and the requirements only; the
history of this session is not evidence.

> Review early and review often.

## Timing

| Situation | Review? |
|---|---|
| A task in a multi-task plan is done | Required |
| A major feature is complete | Required |
| About to merge to main | Required |
| You are stuck and want a fresh angle | Recommended |
| You are about to refactor and want a baseline | Recommended |
| You just fixed a tricky bug | Recommended |

## Procedure

### Step 1: Pin the range

```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or: git merge-base origin/main HEAD
HEAD_SHA=$(git rev-parse HEAD)
```

### Step 2: Read the diff against the checklist

Open [code-reviewer.md](code-reviewer.md) and fill in its placeholders:

- `{DESCRIPTION}`: one line on what was built
- `{PLAN_OR_REQUIREMENTS}`: what the change is supposed to do
- `{BASE_SHA}`: the first commit of the range
- `{HEAD_SHA}`: the last commit of the range

Save what you find in `reports/code-review.md`.

### Step 3: Respond to the findings

1. Critical findings are fixed right away.
2. Important findings are fixed before any further work.
3. Minor findings go on a list for later.
4. A finding that fails on a second look is dropped, and you record why.

## Worked example

```
Situation: Task 2 (a verification function) has just been completed.

Range:
  BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | cut -d' ' -f1)
  HEAD_SHA=$(git rev-parse HEAD)

Checklist inputs:
  DESCRIPTION           = Added verifyIndex() and repairIndex(), four issue types
  PLAN_OR_REQUIREMENTS  = Task 2 of the deployment plan
  BASE_SHA              = a7981ec
  HEAD_SHA              = 3df7661

Written to reports/code-review.md:
  Strengths  - clean structure, tests that exercise real behaviour
  Important  - no progress indicator on long runs
  Minor      - the reporting interval (100) is a magic number
  Verdict    - fine to continue once progress output is added

Next: add the progress output, then start Task 3.
```

## Warning signs

Stop and reconsider if you catch yourself doing any of these:

- skipping the review because the change "is simple"
- waving through a Critical finding
- continuing while an Important finding is still open
- arguing against feedback that is technically correct

When you believe a finding is mistaken, answer it with reasoning, point to the code or
tests that show it works, and ask for clarification where something is still unclear.

The checklist itself lives in [code-reviewer.md](code-reviewer.md).
