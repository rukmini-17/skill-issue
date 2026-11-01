---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

Find the root cause before you attempt a fix. This project keeps source in `src/`, tests in `test/` and settings in `config/app.json`. Run tests with `npm test`.

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

## The Four Phases

Finish each phase before starting the next.

1. **Root cause.** Read the whole error, reproduce it reliably, and check what changed recently. Trace the bad value back to where it starts. See `root-cause-tracing.md`.
2. **Pattern.** Find similar code that works, and list every difference between it and the broken code.
3. **Hypothesis.** State one theory: "I think X is the cause because Y." Test it with the smallest possible change, one variable at a time. If it fails, form a new hypothesis instead of stacking fixes.
4. **Implementation.** Create a failing test first, using the `test-driven-development` skill. Make a single fix at the source, then confirm the suite passes.

If three fixes have failed, stop and question the architecture with your human partner.

## Stop If You Catch Yourself Thinking

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "It's probably X, let me fix that"
- "One more fix attempt"

Each of these means you should return to phase 1.

## When There Is No Root Cause

If the issue really is environmental or timing-dependent, record what you investigated and add handling such as a retry or a clear error message. Most "no root cause" cases are incomplete investigations.

## Supporting Techniques

- `root-cause-tracing.md`: trace bugs backward through the call stack
- `defense-in-depth.md`: add validation at several layers
- `condition-based-waiting.md`: replace arbitrary timeouts with condition polling
