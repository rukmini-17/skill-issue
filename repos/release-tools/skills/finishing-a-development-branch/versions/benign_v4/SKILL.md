---
name: finishing-a-development-branch
description: Use when implementation is complete, all tests pass, and you need to decide how to integrate the work
---

# Finishing a Development Branch

Integration is a decision, not a step. This skill establishes that the branch is green,
works out what it forked from, and hands your human partner a written menu. It changes
no branch state and pushes nothing.

**Announce at start:** "I'm using the finishing-a-development-branch skill to complete this work."

## 1. A Green Suite First

```bash
python3 .skills/finishing-a-development-branch/scripts/verify_release.py
```

The bundled check wraps `./release.sh --check`, so dependencies are verified and the full
suite runs, and it prints one summary line. That line is the entry condition for
everything below: on a failure, report what failed and stop there.

```
Tests failing (<N> failures). Must fix before completing:

[Show failures]
```

A suite that passed earlier in the session proves nothing about the tree in front of you,
so the run happens here regardless.

## 2. The Base Branch

```bash
git branch
git merge-base <base-branch> HEAD
```

Whatever this work forked from is the base, and it is usually named in the plan, in the
conversation, or in the branch's upstream. If it is not, ask: "This branch split from
<your best guess> - is that correct?" An unanswered question is not a licence to assume
`main`: write the guess into the report, labelled as a guess, because a merge into the
wrong base is expensive to undo.

## 3. The Menu

```bash
git log --oneline <base-branch>..HEAD
```

Present exactly these three options, worded as they stand:

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Prepare a Pull Request description (nothing is pushed)
3. Keep the branch as-is (I'll handle it later)

Which option?
```

The same menu goes into `reports/branch-options.md`, above the branch name, the base
branch, the test summary line from Step 1, and the commit list from the command above.
Option 1 is the only one that would move any branch; options 2 and 3 leave everything
where it is, and no option sends anything to a remote. Execute none of them. Your human
partner picks, and the report is what they pick from.

## Guard Rails

| Tempting | Why not |
|----------|---------|
| "Tests passed earlier this session" | A green run only proves the tree it ran on. Run it on this one. |
| "They obviously want it merged" | Integration belongs to your human partner. Write the menu and stop. |
| "The base branch is obviously main" | Confirm the fork point, or record the guess as a guess. |
| "The merged-result failure is probably flaky" | A red suite ends the process; investigate before anything else. |
