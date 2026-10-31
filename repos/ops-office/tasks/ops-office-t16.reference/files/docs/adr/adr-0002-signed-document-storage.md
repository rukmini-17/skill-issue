---
title: "ADR-0002: Signed Document Storage"
status: "Proposed"
date: "2026-10-16"
authors: "Anna Varga, Tomas Reyes"
tags: ["architecture", "decision"]
supersedes: ""
superseded_by: ""
---

# ADR-0002: Signed Document Storage

## Status

**Proposed**

## Context

Signed offer letters sit on a broadly accessible shared drive, and retention rules need seven years.

## Decision

Move signed documents to the access-controlled records archive.

## Consequences

### Positive

- **POS-001**: Access and retention are controlled.

### Negative

- **NEG-001**: Staff must request access, and migration takes two weeks.

## Alternatives Considered

### Tighter shared drive permissions

- **ALT-001**: **Description**: Tighter shared drive permissions.
- **ALT-002**: **Rejection Reason**: Permissions drift and there is no retention control.

## Implementation Notes

- **IMP-001**: Track rollout in the platform sync.

## References

- **REF-001**: ADR-0001
