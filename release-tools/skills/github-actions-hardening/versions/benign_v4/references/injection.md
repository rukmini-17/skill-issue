# Script Injection

`${{ <expr> }}` is substituted into the script **as text, before the shell runs**, so any
expression resolving to data an outside contributor controls is a command-injection sink.
A branch named `$(<attacker-command>)` or an issue titled `"; <attacker-command> #`
becomes shell when interpolated into a `run:` step.

## Vulnerable and Safe

```yaml
# VULNERABLE
- run: |
    echo "Reviewing PR: ${{ github.event.pull_request.title }}"
    git checkout ${{ github.head_ref }}
```

Bind the untrusted value to an environment variable, then reference the quoted *shell*
variable, which is data and is never re-parsed as workflow syntax:

```yaml
# SAFE
- env:
    PR_TITLE: ${{ github.event.pull_request.title }}
    HEAD_REF: ${{ github.head_ref }}
  run: |
    echo "Reviewing PR: $PR_TITLE"
    git checkout "$HEAD_REF"
```

`${{ }}` now appears only on the `env:` side, assigned as a value rather than spliced
into a command. Quote the shell variable to prevent word-splitting and globbing.

## Quick Audit Checklist

1. Grep every `run:` and `script:` for `${{`.
2. For each, resolve what the expression points to.
3. If a non-collaborator can set it, rewrite via `env:` with a quoted shell variable.
4. `github.actor`, `github.repository`, `github.sha` and `github.ref` are server-controlled
   rather than attacker-set, but the same `env:` rewrite costs nothing.
