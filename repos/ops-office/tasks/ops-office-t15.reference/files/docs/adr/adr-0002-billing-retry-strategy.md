---
title: "ADR-0002: Billing Retry Strategy"
status: "Proposed"
date: "2026-10-08"
authors: "Jun Tanaka, Marek Lindqvist, Anna Varga"
tags: ["architecture", "decision"]
supersedes: ""
superseded_by: ""
---

# ADR-0002: Billing Retry Strategy

## Status

**Proposed**

## Context

The September outage came from unbounded retries against the tax service.

## Decision

Use capped exponential backoff, at most 5 attempts, then a dead-letter queue.

## Consequences

### Positive

- **POS-001**: A struggling service is no longer hammered.

### Negative

- **NEG-001**: Finance gains a daily manual review step.

## Alternatives Considered

### Fixed-interval retries

- **ALT-001**: **Description**: Fixed-interval retries.
- **ALT-002**: **Rejection Reason**: They keep hammering a struggling service.

## Implementation Notes

- **IMP-001**: Track rollout in the platform sync.

## References

- **REF-001**: ADR-0001
