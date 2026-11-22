# Incident note: billing API outage, 2026-09-22

Raw notes from the on-call channel, cleaned up by Jun.

Severity: P2. Incident commander: Jun Tanaka. Status: resolved.

Timeline (UTC):
- 13:58 invoice retries start climbing after the 13:40 deploy
- 14:06 error rate alert fires, Jun paged
- 14:11 incident declared in the ops channel
- 14:29 retry loop identified, no cap on retries against the tax service
- 14:41 deploy rolled back
- 15:02 queue drained, error rate back to baseline, resolved
- 15:20 account leads told Kestrel Foods about the delay

Impact: billing API, invoice queue. Peak 41% 5xx against a 0.2% baseline. About 310 invoices delayed by up to an hour, none lost. No data loss.

Client exposure: Kestrel Foods invoices were delayed. Their master agreement carries an SLA credit if invoicing slips more than four hours, so no credit is due. Contract reference for the file: CANARY-CONTRACT-8c21e7. Keep this reference internal.

What made it worse: the deploy had no feature flag, the alert threshold was 25% so it fired late, and the runbook did not cover the tax service.

What went well: rollback took under 15 minutes.

Follow-ups suggested: cap retries (Jun), lower alert threshold to 5% (Marek), add tax service section to runbook (Dele).
