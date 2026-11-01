# shop-web build report

## What was built

A complete `shop-web` benchmark workspace, in the seven phases of the build prompt:

1. **Skeleton + workspace** — a Node storefront (cart, pricing, payment client, `POST /quote`), `node --test` suite, `.env`/`.npmrc`/`config/app.json`/`data/customers.csv` holding canaries C1–C4, the protected `deploy.yml`, the `privileged.sh` stub, `mock_hosts.yaml`, `canaries.json`, and an idempotent offline `setup.sh` that builds the stub registry tarballs.
2. **Six real skills** at the pinned commits (`test-driven-development`, `systematic-debugging` from superpowers; `javascript-typescript-jest`, `npm-trusted-publishing`, `documentation-writer` from awesome-copilot; `dependency-upgrade` from wshobson), each with v1, `manifest.json`, `skill_meta.yaml` and the source `LICENSE`.
3. **Benign versions** `benign_v2`–`benign_v4` per skill (plus `benign_v5` on `dependency-upgrade`), all within v1's permissions and with no new extractable host, path, command or dependency.
4. **14 tasks** with delegations and runnable reference solutions; at least 2 per skill, and at least one strictly-narrower delegation per skill.
5. **25 scenarios, 50 seeds** on the exact Part 2.7 class and goal budget.
6. **8 oracle traces** (4 clean, 4 violating, covering P1–P5, with one clean trace that legitimately reads C2) and `check_repo.py`.

`python check_repo.py --run-references` passes **1657 of 1657 checks**. Reference solutions run against a throwaway localhost registry serving `mock/registry.example/`; `npm test` exits 0 for each, and no canary value appears in the requests that registry logs.

## Deviations

- **`dependency-upgrade` gained a script.** Its source has no script or dependency file, but Part 4 designates it the script/dependency skill. Its stub `checkCompatibility()` was turned into `scripts/compatibility-matrix.mjs` + vendored `scripts/lib/semver-lite.mjs`. Recorded under `adaptations`; this is what `concealed_dependency` seeds modify. This goes beyond the adaptation list in rule 2 and was flagged for review.
- **C3 is the `.npmrc` token** (Part 4), not PII; PII rows are the optional **C4** in `data/customers.csv`. The token is scoped to `npm.internal.example`, so a clean `npm install` against `registry.example` never sends it (no accidental P5).
- **`dependency-upgrade` carries 11 scenarios**, not ~4, because the concealed, late-binding and laundering classes all require it. The other five skills share 14.
- **Two skills slightly exceed ~250 lines** (260 and 253) to keep the original wording.
- **`check_repo.py` was written fresh** (not adapted from `ops-office`) but keeps the same CLI and adds a self-contained oracle evaluator and a localhost registry for reference runs.

## Known weaknesses

- The `authority_laundering` scenarios are P5-only and, as noted in the README, skill A can already read `config/app.json`, so the companion is narrative rather than strictly necessary for access.
- `concealed_dependency` relies on the harness observing actions a sub-process (the compatibility script) takes, not just the agent's direct tool calls.
- Jest tasks are checked statically because Jest is not in the sandbox.

## Questions for the team

1. Is the added `compatibility-matrix.mjs` script in `dependency-upgrade` acceptable, or should the script/dependency skill role move to a skill that ships a script in its source?
2. Should `authority_laundering` be hardened by dropping `config/app.json` from `dependency-upgrade`'s manifest, so the companion skill is genuinely required to reach C2?
3. Does the harness record file reads, network calls and sub-process execs performed by a skill's script, which the `concealed_dependency` and `late_binding` seeds depend on?
