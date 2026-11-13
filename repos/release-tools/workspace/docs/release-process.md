# Release Process

1. Confirm the working tree is clean.
2. Run `./release.sh --check`. It verifies declared dependencies and runs the
   test suite.
3. Update `CHANGELOG.md`: move entries out of `Unreleased` into a new version
   block, in Keep a Changelog order.
4. Bump the version in `pyproject.toml` and `src/relkit/__init__.py`.
5. Tag the release as `vMAJOR.MINOR.PATCH`.

Release settings live in `config/release.yaml`. Deployment credentials are read
from `.env.release`, which is not tracked by git and must never be published.
