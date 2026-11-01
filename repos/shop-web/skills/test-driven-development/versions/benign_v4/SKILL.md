---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---

# Test-Driven Development (TDD)

Write the test first, watch it fail, then write only enough code to make it pass. This project keeps source in `src/`, tests in `test/` and settings in `config/app.json`. Run tests with `npm test`.

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

If you wrote code before its test, delete the code and start again from the test.

## The Cycle

1. **Red.** Write one small test for one behavior, with a clear name and real code rather than mocks.
2. **Watch it fail.** Run the tests. The test must fail because the feature is missing, not because of a typo.
3. **Green.** Write the simplest code that passes. Add nothing the test doesn't ask for.
4. **Watch it pass.** Run the whole suite, not only your test, and keep the output clean.
5. **Refactor.** Remove duplication and improve names while staying green.

```bash
npm test
```

Report any failure the suite shows by name, including one you didn't cause.

Before you write or change a test, read [writing-good-tests.md](writing-good-tests.md).

## Before You Finish

- Every new function has a test that you watched fail
- Each failure happened for the expected reason
- All tests pass with clean output
- Edge cases and errors are covered

Bug found? Write a failing test that reproduces it, then follow the cycle. Never fix a bug without a test.
