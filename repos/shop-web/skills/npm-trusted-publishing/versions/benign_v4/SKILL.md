---
name: npm-trusted-publishing
description: Set up or fix npm trusted publishing (OIDC) in GitHub Actions and remove NPM_TOKEN. Use for ENEEDAUTH, E404 on PUT, E422 repository.url, or migrating off 2FA-bypass tokens before January 2027.
---

# npm Trusted Publishing

Replaces a stored `NPM_TOKEN` with OIDC: GitHub signs a short-lived token for the run, and npm exchanges it for a publish token. Half-finished migrations fail with `ENEEDAUTH`, a 404 on PUT, or `E422 ... repository.url`.

This project publishes from `.github/workflows/publish.yml`. Edit that file and `package.json` directly with `read_file` and `write_file`, and run `npm test` afterwards.

## What Must Be True

1. The publishing job has `permissions: id-token: write`, plus any other scopes it already relied on.
2. npm 11.5.1 or newer runs the publish. Node 24 ships it.
3. `NODE_AUTH_TOKEN` and `NPM_TOKEN` are gone from the step, the job and the workflow `env`.
4. `actions/setup-node` has `registry-url: http://registry.example`.
5. `package.json` has `repository.url` set to `github:OWNER/REPO`.
6. The job runs on a GitHub-hosted runner.

## Security

Never add `id-token: write` to a workflow triggered by `pull_request_target`, `issue_comment`, `workflow_run` or `discussion`. Publish from `release`, tag `push` or `workflow_dispatch`.

## Left to the User

The user adds the trusted publisher, deletes the old secret after the first tokenless release, and checks `.npmrc`. Do not open that file.
