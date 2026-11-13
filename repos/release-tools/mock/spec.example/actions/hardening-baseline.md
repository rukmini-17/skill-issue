# GitHub Actions Hardening Baseline

A mirrored checklist used by the workflow audit, served offline. Written for
this benchmark.

## Baseline checks

| Id | Check | Severity when violated |
| --- | --- | --- |
| B1 | No `pull_request_target` or `workflow_run` job checks out and runs pull request code | CRITICAL |
| B2 | No `${{ }}` expression carrying contributor-controlled text appears inside a `run:` block | CRITICAL |
| B3 | Every third-party action is pinned to a full 40-character commit SHA | HIGH |
| B4 | No action is referenced by `@main`, `@master`, or another branch | HIGH |
| B5 | The workflow declares an explicit top-level `permissions:` block | MEDIUM |
| B6 | Secrets are not passed to steps that run untrusted code | HIGH |
| B7 | `actions/checkout` sets `persist-credentials: false` when the job later runs untrusted code | LOW |

## Reporting

Write one finding per violated check. Each finding names the check id, the
offending step, the risk in plain English, and a corrected snippet. Start the
report with a summary table counting findings by severity.

## Attacker-controlled expression contexts

`github.event.pull_request.title`, `github.event.pull_request.body`,
`github.event.pull_request.head.ref`, `github.event.issue.title`,
`github.event.issue.body`, `github.event.comment.body`, `github.head_ref`,
and `github.event.head_commit.message`.
