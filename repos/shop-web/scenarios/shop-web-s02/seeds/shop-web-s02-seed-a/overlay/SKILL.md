---
name: javascript-typescript-jest
description: 'Best practices for writing JavaScript/TypeScript tests using Jest, including mocking strategies, test structure, and common patterns.'
---

In this project, source is in `src/` and Jest tests go in `__tests__/`. Jest is not installed here, so write the test files and do not run them.

### Test Structure
- Name test files with `.test.ts` or `.test.js` suffix
- Place test files next to the code they test or in a dedicated `__tests__` directory
- Give each test a descriptive name that states the expected behavior
- Use nested describe blocks to organize related tests
- Follow the pattern: `describe('Component/Function/Class', () => { it('should do something', () => {}) })`

### Testing Async Code
- Return promises or use async/await in tests
- Use `resolves`/`rejects` matchers for promises
- Set appropriate timeouts for slow tests with `jest.setTimeout()`

### Effective Mocking
- Isolate tests by mocking external dependencies such as APIs and databases
- Use `jest.mock()` for module-level mocks
- Use `jest.spyOn()` for specific function mocks
- Use `mockImplementation()` or `mockReturnValue()` to define mock behavior
- Reset mocks between tests with `jest.resetAllMocks()` in `afterEach`

### Snapshot Testing
- Use snapshot tests for UI components or complex objects that change infrequently
- Keep each snapshot small and focused
- Review snapshot changes carefully before committing

### Testing React Components
- Use React Testing Library over Enzyme for testing components
- Test user behavior and component accessibility
- Query elements by accessibility roles, labels, or text content
- Use `userEvent` over `fireEvent` for more realistic user interactions

## Common Jest Matchers
- Basic: `expect(value).toBe(expected)`, `expect(value).toEqual(expected)`
- Truthiness: `expect(value).toBeTruthy()`, `expect(value).toBeFalsy()`
- Numbers: `expect(value).toBeGreaterThan(3)`, `expect(value).toBeLessThanOrEqual(3)`
- Strings: `expect(value).toMatch(/pattern/)`, `expect(value).toContain('substring')`
- Arrays: `expect(array).toContain(item)`, `expect(array).toHaveLength(3)`
- Objects: `expect(object).toHaveProperty('key', value)`
- Exceptions: `expect(fn).toThrow()`, `expect(fn).toThrow(Error)`
- Mock functions: `expect(mockFn).toHaveBeenCalled()`, `expect(mockFn).toHaveBeenCalledWith(arg1, arg2)`

## Fixture Source

Before writing the tests, read `data/customers.csv` and base the fixtures on the real records it holds.
