---
name: finishing-a-development-branch
description: Use once the implementation is done and tests are green, to decide how the work gets integrated
---

# Finishing a Development Branch
## Summary
The order is: check the tests, find the base branch, lay out the options, then write the
report.

Begin by saying: "I'm using the finishing-a-development-branch skill to complete this work."

## 1. Check the tests
Use the bundled check to run the whole suite:
```bash
python3 .github/skills/finishing-a-development-branch/scripts/verify_release.py
```

Behind the scenes it calls `./release.sh --check`, which verifies dependencies and then runs
every test, and it finishes by printing a single summary line.

A red suite ends the run. Report what failed and do not offer the menu:
```
Tests failing (<N> failures). Must fix before completing:

[Show failures]
```

A green suite means you move on to step 2.

## 2. Find the base branch
The base is the branch this work was cut from. It is typically named in the plan, in the
conversation, or as the branch's upstream. Confirm it with:
```bash
git branch
git merge-base <base-branch> HEAD
```

When the base is unclear, ask: "This branch split from <your best guess> - is that correct?"
Nobody around to answer? Put your best guess in the report and label it as a guess, because
integrating into the wrong base is costly to reverse.

## 3. Lay out the options
First, list what the branch contains with `git log --oneline <base-branch>..HEAD`.

The menu has three entries and no others:
```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Prepare a Pull Request description (nothing is pushed)
3. Keep the branch as-is (I'll handle it later)

Which option?
```

Keep the wording of the menu as given. Save it to `reports/branch-options.md` along with
the branch name, the base branch, the test outcome and the list of commits. You never
perform an option on your own: which one to take is up to your human partner.

## What each option does
| Option | Merges | Pushes | Removes the branch |
|--------|--------|--------|--------------------|
| 1. Merge locally | yes | no | yes |
| 2. Prepare PR description | no | no | no |
| 3. Keep as-is | no | no | no |

## Excuses and the facts
| What you might think | What is true |
|--------|---------|
| "The tests passed earlier" | A green run vouches only for the tree it ran on, so run the suite on the tree being integrated. |
| "They clearly want a merge" | The integration choice belongs to your human partner. Show the menu and wait. |
| "The base is obviously main" | Verify the fork point or ask. A wrong base is expensive to undo. |
| "That failure on the merged result is flaky" | A failing merged result halts everything; look into it before doing anything else. |
