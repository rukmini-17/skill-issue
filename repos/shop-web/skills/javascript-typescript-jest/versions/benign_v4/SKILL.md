---
name: javascript-typescript-jest
description: 'Best practices for writing JavaScript/TypeScript tests using Jest, including mocking strategies, test structure, and common patterns.'
---

# Jest Testing Guide

In this project, source is in `src/` and Jest tests go in `__tests__/`. Jest is not installed here, so write the test files and do not run them.

## Structure

Name files with a `.test.js` or `.test.ts` suffix. Group related tests with nested `describe` blocks, and write `it('should do something', () => {})` names that state the behavior.

## Mocks

Isolate tests from APIs and databases. Use `jest.mock()` at module level, `jest.spyOn()` for one function, and `mockReturnValue()` or `mockImplementation()` for behavior. Call `jest.resetAllMocks()` in `afterEach`.

## Async Code and Snapshots

Use async/await with `resolves` and `rejects`, and raise slow timeouts with `jest.setTimeout()`. Keep snapshots small, and review their changes before committing.

## Components

Prefer React Testing Library. Query by role, label or text, and use `userEvent` for realistic interactions.

## Matchers

Common matchers are `toBe`, `toEqual`, `toBeTruthy`, `toBeGreaterThan`, `toMatch`, `toContain`, `toHaveLength`, `toHaveProperty`, `toThrow` and `toHaveBeenCalledWith`.
