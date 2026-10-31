---
title: "ADR-0001: Route Planner Hosting"
status: "Accepted"
date: "2026-03-12"
authors: "Marek Lindqvist (Platform)"
tags: ["architecture", "decision"]
supersedes: ""
superseded_by: ""
---

# ADR-0001: Route Planner Hosting

## Status

**Accepted**

## Context

The route planner runs on a single depot server that has no failover.

## Decision

Use the vendor's hosted edition with per-seat licensing.

## Consequences

### Positive

- **POS-001**: No depot hardware to maintain.

### Negative

- **NEG-001**: Route planning depends on the depot's internet link.

## Alternatives Considered

### Second depot server

- **ALT-001**: **Description**: Add a standby server at Dartmouth.
- **ALT-002**: **Rejection Reason**: Hardware and upkeep cost more than the licence.

## Implementation Notes

- **IMP-001**: Migrated over one weekend in April.

## References

- **REF-001**: None
