# Triggers and Privilege

The single most important question for workflow security is: **can an outside contributor trigger
this workflow, and if so, what token and secrets does it get?** GitHub answers this differently per
trigger.

## Trust Matrix

| Trigger | Who can fire it | `GITHUB_TOKEN` | Secrets available | Risk |
| --- | --- | --- | --- | --- |
| `push` | Repo collaborators | read/write | yes | Low — trusted authors |
| `pull_request` (same-repo branch) | Collaborators | read/write | yes | Low |
| `pull_request` (from a fork) | **Anyone** | **read-only** | **no** | Low by design — even malicious code can't steal anything |
| `pull_request_target` | **Anyone with a fork** | **read/write** | **yes** | **High** — runs in base-repo context |
| `workflow_run` | Fires after another workflow | **read/write** | **yes** | **High** |
| `issue_comment`, `issues` | **Anyone** | **read/write** | **yes** | **High** |

The trap: `pull_request` from a fork is *safe* because GitHub deliberately strips the token down
and withholds secrets. Maintainers who find that "the secrets don't work on fork PRs" often switch
to `pull_request_target` to get them back — and in doing so hand a write token and every secret to
arbitrary contributors.

## Rules

* Treat `pull_request_target`, `workflow_run`, `issue_comment`, and `issues` as privileged.
* In a privileged workflow, **never** check out and execute PR/fork code.
* If you only need to label, comment, or triage based on metadata, that is fine — just don't run
  the contributor's code.
* Prefer `pull_request` (with its safe read-only/no-secrets defaults) whenever possible.
