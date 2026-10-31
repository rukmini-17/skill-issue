# Post-Mortem: Billing API outage

**Date:** 2026-09-22
**Severity:** P2
**Duration:** 56 minutes (14:06 UTC - 15:02 UTC)
**Incident Commander:** Jun Tanaka
**Status:** Resolved

## Summary

A deploy introduced unbounded retries against the tax service. About 310 invoices were delayed by up to an hour and none were lost. Rolling back resolved it.

## Root Cause

The retry path had no cap, so a slow tax service produced a retry loop.

## Contributing Factors

- The alert threshold of 25% fired late.

## What Went Well

- Rollback took under 15 minutes.

## Action Items

| # | Action | Owner | Due Date | Priority |
|---|--------|-------|----------|----------|
| 1 | Cap retries against the tax service | Jun Tanaka | 2026-11-15 | High |
