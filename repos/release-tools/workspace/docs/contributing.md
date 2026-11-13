# Contributing

- Write commit subjects as Conventional Commits: `type(scope): summary`.
- Keep one logical change per commit.
- Add or update tests for every behaviour change.
- Run `./release.sh --check` before you open a pull request.
- Never commit `.env.release` or any other credential file.

Contributor records are kept in `data/contributors.csv`. That file holds
personal data and is not used by the build.

## Checklist

- [ ] Tests added or updated
- [ ] `./release.sh --check` passes
- [ ] CHANGELOG entry added under `Unreleased`
