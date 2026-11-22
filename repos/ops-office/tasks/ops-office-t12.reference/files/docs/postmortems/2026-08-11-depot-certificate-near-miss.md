# Post-Mortem: Depot certificate near miss

**Date:** 2026-08-11
**Severity:** P4
**Duration:** 68 minutes (09:12 UTC - 10:20 UTC)
**Incident Commander:** Marek Lindqvist
**Status:** Resolved

## Summary

A weekly review found a depot gateway certificate two days from expiry. It was replaced before any impact. Missing it would have stopped about 40 handhelds checking in.

## Root Cause

No expiry alert covered this gateway, and renewals were tracked by hand.

## Contributing Factors

- Renewals relied on a manual process.

## What Went Well

- The weekly review caught it.

## Action Items

| # | Action | Owner | Due Date | Priority |
|---|--------|-------|----------|----------|
| 1 | Add expiry alerts for all gateways | Marek Lindqvist | 2026-11-15 | High |
