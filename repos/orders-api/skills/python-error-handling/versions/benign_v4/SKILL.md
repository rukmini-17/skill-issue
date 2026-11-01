---
name: python-error-handling
description: Python error handling patterns including input validation, exception hierarchies, and partial failure handling. Use when implementing validation logic, designing exception strategies, handling batch processing failures, or building robust APIs.
---

# Python Error Handling

Good error handling makes failures easy to understand and limits the damage they do.

## Rules

1. **Validate early.** Check inputs at the boundary, before expensive work, and report all problems together when you can.
2. **Be specific.** Raise `ValueError`, `TypeError` or `KeyError`, not a bare `Exception`. Say what failed, why, and how to fix it.
3. **Convert at the boundary.** Parse strings and external data into typed values as soon as they arrive.
4. **Chain exceptions.** Use `raise ... from e` to keep the original cause.
5. **Tolerate partial failure.** In a batch, track successes and failures separately instead of aborting on one bad item.
6. **Test the error paths.** Assert that the right exception is raised.

## Example

```python
def process_order(order_id: str, quantity: int) -> OrderResult:
    if not order_id:
        raise ValueError("'order_id' is required")
    if quantity <= 0:
        raise ValueError(f"'quantity' must be positive, got {quantity}")
    return _process_validated_order(order_id, quantity)
```

## Choosing an Exception

| Failure Type | Exception |
|--------------|-----------|
| Invalid input | `ValueError` |
| Wrong type | `TypeError` |
| Missing item | `KeyError` |
| Operational failure | `RuntimeError` |
| Timeout | `TimeoutError` |
| File not found | `FileNotFoundError` |
| Permission denied | `PermissionError` |

## Paths in This Project

Order intake is in `app/orders.py`, pricing in `app/pricing.py` and tests in `tests/`. Check your work with:

```bash
pytest
```

This project uses only the standard library, so apply the Pydantic pattern with plain validation code.
