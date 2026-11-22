---
name: git-commit
description: 'Use this skill when the user wants to make a Git commit or split changes into more than one commit. Also use it when the user types "/commit" or asks for a conventional commit. The skill examines the diff, stages the related files, writes a Conventional Commits message, and runs git commit. Do not use it when the user wants only a commit message and no commit. Do not use it to push, open a pull request, rebase, or change the commit history.'
license: MIT
compatibility: 'Requires Git. The `--resolved` option of `git add` requires Git 2.56 or later.'
allowed-tools: shell(git:*)
---

# Git Commit with Conventional Commits

Commit in the [Conventional Commits 1.0.0](http://spec.example/conventional-commits/1.0.0.md)
style, taking the type, the scope and the summary from the diff rather than from the
conversation.

## Workflow

**Step 1. Read the repository rules.** A commitlint configuration
(`commitlint.config.js` or `.commitlintrc.json`) comes first, then `CONTRIBUTING.md`,
then the recent messages:

```bash
git log --oneline -10
```

Where a repository rule differs from this skill, the repository rule wins.

**Step 2. Examine the changes.**

```bash
git status --porcelain
git diff --staged
git diff
```

With no changes, say so and stop; an empty commit is not the answer.

**Step 3. Stage one logical change.** When the index already holds more than one change,
unstage the others before adding yours:

```bash
git reset -q -- path/to/other-file1 path/to/other-file2
git add -- path/to/file1 path/to/file2
git add -- '*.test.*'
git add -- src/components/
```

An unquoted glob is expanded by the shell, which misses files in subdirectories, so
quote it. `git add -p` and `git add -i` both wait for a person and cannot be used here.
After a merge conflict, `git add --resolved` stages the resolved files only and stops on
one that still carries conflict markers. Read the staged list back with
`git diff --staged --name-only`; secrets such as `.env` files, `credentials.json` and
private keys never belong in a commit.

**Step 4. Write the message**, in the format below.

**Step 5. Commit,** one `-m` per paragraph, which Git separates with blank lines. The
form works the same in Bash and PowerShell. A long message goes to a temporary file,
committed with `git commit -F <file>`.

```bash
git commit -m "feat(auth): add token refresh"
git commit -m "fix(parser): accept empty input" -m "An empty file caused a crash." -m "Closes: #123"
```

**Step 6. Confirm the result.**

```bash
git log -1 --stat
git status --porcelain
```

## The Message

```text
<type>(<scope>): <summary>

<body>

<footer>
```

Scope, body and footer are each optional; without a scope the line is
`<type>: <summary>`. The summary is imperative ("add", never "added" or "adds"), at most
72 characters, and carries no closing period. The body covers what changed and why. A
footer reads `Token: value` or `Token #value` (`Refs: #456`, `Closes #123`): Conventional
Commits accepts both, Git reads only the first as a trailer, and a token spells spaces
as `-`.

Conventional Commits itself defines `feat` and `fix`. The remaining types come from the
Angular convention (`@commitlint/config-conventional`): `docs` for documentation alone,
`style` for formatting that leaves logic untouched, `refactor` for a change that is
neither feature nor fix, `perf` for performance, `test` for tests, `build` for the build
system or dependencies, `ci` for CI configuration, `chore` for other maintenance, and
`revert` for undoing an earlier commit. A repository with its own list overrides this
one.

A breaking change takes `!` before the colon or a `BREAKING CHANGE:` footer in uppercase
(`BREAKING-CHANGE:` is equally correct):

```text
feat(api)!: remove the v1 endpoints

BREAKING CHANGE: Clients must use the v2 endpoints.
```

## Safety Rules

The Git configuration stays as it is. `--no-verify` is used only on the user's
instruction, since hooks live in `.git/hooks` or in the configuration. A failing hook
means no commit was made: fix the problem, stage again, and repeat the same
`git commit` command rather than reaching for `--amend`, which rewrites the previous
commit. History is rewritten only on the user's instruction, which rules out
`git reset --hard`, `git rebase` and the experimental `git history` command by default.
Pushing likewise waits for the user to ask, and a force push to the default branch never
happens.
