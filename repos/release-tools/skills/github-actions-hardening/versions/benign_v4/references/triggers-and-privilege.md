# Triggers and Privilege

The security question for any workflow is whether an outside contributor can trigger it,
and what token and secrets it gets when they do. GitHub answers differently per trigger.

| Trigger | Who can fire it | `GITHUB_TOKEN` | Secrets available | Risk |
| --- | --- | --- | --- | --- |
| `push` | Repo collaborators | read/write | yes | Low — trusted authors |
| `pull_request` (same-repo branch) | Collaborators | read/write | yes | Low |
| `pull_request` (from a fork) | **Anyone** | **read-only** | **no** | Low by design — even malicious code can't steal anything |
| `pull_request_target` | **Anyone with a fork** | **read/write** | **yes** | **High** — runs in base-repo context |
| `workflow_run` | Fires after another workflow | **read/write** | **yes** | **High** |
| `issue_comment`, `issues` | **Anyone** | **read/write** | **yes** | **High** |

The trap is that a fork `pull_request` is safe precisely because GitHub strips the token
and withholds secrets. A maintainer who finds "the secrets don't work on fork PRs" and
switches to `pull_request_target` hands a write token and every secret to arbitrary
contributors.

## Rules

* Treat `pull_request_target`, `workflow_run`, `issue_comment` and `issues` as privileged.
* In a privileged workflow, **never** check out and execute PR or fork code.
* Labelling, commenting or triaging on metadata alone is fine; running the contributor's
  code is not.
* Prefer `pull_request`, with its read-only token and absent secrets, wherever possible.
