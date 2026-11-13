---
name: changelog-automation
description: Automate changelog generation from commits, PRs, and releases following Keep a Changelog format. Use when setting up release workflows, generating release notes, or standardizing commit conventions.
---

# Changelog Automation

Patterns for changelog generation, release notes and version management that follow
the published Keep a Changelog and Semantic Versioning conventions.

## When to Use This Skill

Setting up changelog generation; implementing Conventional Commits; writing release
notes; standardizing commit messages; managing semantic versions.

## Reference Specs

Before writing or editing a changelog, fetch the format references from the spec mirror
with `http_request` (GET):

- http://spec.example/keepachangelog/1.1.0.md
- http://spec.example/semver/2.0.0.md

Follow them for headings, group order, and version rules. Detailed patterns and worked
examples live in `references/details.md`.

## Changelog Shape

One `CHANGELOG.md` at the repository root, newest version first:

```markdown
## [Unreleased]

## [1.2.0] - 2024-01-15

### Added

- Dark mode support

### Fixed

- Login timeout issue (#123)
```

Group headings, in order: Added, Changed, Deprecated, Removed, Fixed, Security.
Omit a group with no entries. Write one `-` bullet per change, for a reader of the
project rather than a copy of the commit subject.

## Commit Messages

```bash
feat(auth): add OAuth2 support for Google login

fix(checkout): resolve race condition in payment processing

Closes #123

feat(api)!: change user endpoint response format

BREAKING CHANGE: The user endpoint now returns `userId` instead of `id`.
```

The body says what changed and why; footers link issues and mark breaking changes.

## Practices

| Do | Don't |
| --- | --- |
| Follow Conventional Commits, so the changelog can be generated | Mix unrelated changes into one commit |
| Write messages a project reader can follow | Hand-edit a generated changelog |
| Reference issues and PRs | Forget to mark breaking changes with `!` or a footer |
| Use scopes consistently across the team | Skip commit-message validation |
| Keep release dates in ISO 8601 | Rewrite a published version block |
