---
name: bug-reproduction-brief
description: 'Turn a vague, intermittent, or environment-specific bug report into a minimal evidence-backed reproduction before proposing a fix.'
---

# Bug Reproduction Brief

Use this for bug reports that are incomplete, intermittent, environment-specific or mixed with an assumed cause. A verified reproduction is the whole deliverable: do not edit implementation code, because that can destroy the evidence.

In this project, bug reports are in `issues/`, the code is in `app/`, the existing tests are in `tests/` and the runtime configuration is `config/app.yaml`.

## Steps

1. **Capture the failure.** Note the exact error or wrong output, the affected command and the smallest known input. Mark second-hand claims as unverified, and keep secrets and personal data out.
2. **Record the environment.** Only state what you can inspect, and never guess credentials or production configuration.

   ```bash
   python3 --version
   python3 -m pip --version
   pytest --version
   ```

3. **State expected and actual.** Write each as an observable result, with no suspected cause in either.
4. **Reduce.** Remove unrelated data and steps one at a time until you have the smallest failing fixture. Put it in `reports/test_repro.py`.
5. **Repeat.** Run `pytest reports/test_repro.py` at least twice where safe. If the failure is intermittent, give its frequency rather than calling it deterministic.

## Output

Write the brief to `reports/bug_brief.md`, with these fields: target and commit, environment, expected, actual, minimal steps, minimal fixture, reproduced (yes, no or intermittent), evidence, unknowns, and a safe next hypothesis to test.

## Boundaries

Do not change production data to reproduce a bug. Do not publish secrets, customer records or private source. Do not claim a root cause from correlation alone. Stop once the reproduction is verified.

## Source and licence

Adapted from the MIT-licensed workflow in the skyestrela/ai-agent-skill-preview repository on GitHub.
