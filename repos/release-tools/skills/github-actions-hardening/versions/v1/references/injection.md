# Script Injection

`${{ <expr> }}` is substituted into the script **as text, before the shell runs**. Any expression
that resolves to data an outside contributor controls is therefore a command-injection sink.

## The Vulnerable Pattern

```yaml
# VULNERABLE
- run: |
    echo "Reviewing PR: ${{ github.event.pull_request.title }}"
    git checkout ${{ github.head_ref }}
```

## The Safe Pattern — Pass Through `env:`

Bind the untrusted value to an environment variable, then reference the *shell* variable (quoted).
The shell variable is data, never re-parsed as workflow syntax:

```yaml
# SAFE
- env:
    PR_TITLE: ${{ github.event.pull_request.title }}
    HEAD_REF: ${{ github.head_ref }}
  run: |
    echo "Reviewing PR: $PR_TITLE"
    git checkout "$HEAD_REF"
```

`${{ }}` now appears only on the `env:` side, where it is assigned as a value rather than spliced
into a command. Always quote the shell variable (`"$PR_TITLE"`) to prevent word-splitting and
globbing.

## Quick Audit Checklist

1. Grep every `run:` and `script:` for `${{`.
2. For each, resolve what the expression points to.
3. If it can be set by a non-collaborator → rewrite via `env:` with a quoted shell variable.
4. `github.actor`, `github.repository`, `github.sha`, `github.ref` (for branch protection contexts)
   and similar server-controlled values are not attacker-set, but a defense-in-depth `env:` rewrite
   costs nothing.
