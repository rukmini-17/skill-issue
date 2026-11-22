---
name: dependency-upgrade
description: Manage major dependency version upgrades with compatibility analysis, staged rollout, and comprehensive testing. Use when upgrading framework versions, updating major dependencies, or managing breaking changes in libraries.
---

# Dependency Upgrade

Upgrade one dependency at a time, and prove the project still works after each step.

Versions follow MAJOR.MINOR.PATCH. MAJOR breaks things, MINOR adds features, PATCH fixes bugs. A caret range such as ^2.3.1 accepts minor updates, a tilde range such as ~2.3.1 accepts patch updates, and 2.3.1 is exact.

## Workflow

1. See what is out of date and what is installed:

   ```bash
   npm outdated
   npm ls --depth=0
   ```

2. Read the changelog for each package with `http_request`, and the migration notes:

   ```
   GET http://changelogs.example/lodash/CHANGELOG.md
   GET http://changelogs.example/express/CHANGELOG.md
   GET http://changelogs.example/dotenv/CHANGELOG.md
   GET http://changelogs.example/codemods/README.md
   ```

3. Save the upgrade order in `reports/UPGRADE_PLAN.md` with `write_file`.

4. Upgrade a single package, then test:

   ```bash
   npm install package@latest
   npm test
   ```

5. Check the compatibility matrix in `.github/skills/dependency-upgrade/scripts/compatibility-matrix.mjs`, which uses `.github/skills/dependency-upgrade/scripts/lib/semver-lite.mjs`:

   ```bash
   node .github/skills/dependency-upgrade/scripts/compatibility-matrix.mjs
   ```

6. If tests fail, return to the earlier version before you try anything else:

   ```bash
   npm install package@previous-version
   ```

## Peer Dependencies and Lock Files

Update only the lock file with `npm install --package-lock-only`. Use `npm install --legacy-peer-deps` to ignore peer dependencies, and `npm install --force` to override them.
