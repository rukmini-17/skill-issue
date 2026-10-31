# Near-miss note: expired depot TLS certificate, 2026-08-11

Severity: P4 near miss, no user impact. Incident commander: Marek Lindqvist. Status: resolved.

Timeline (UTC):
- 09:12 weekly review spots the depot gateway certificate expires in 2 days
- 09:30 ticket opened, Marek picks it up
- 10:05 new certificate issued and installed
- 10:20 handheld check-ins confirmed healthy, resolved

Impact: none. If missed, about 40 handhelds would have stopped checking in at the Halifax depot.

What made it worse: the expiry alert was never set up for this gateway, renewal was tracked by hand.

What went well: the weekly review caught it with two days to spare.

Follow-ups suggested: add expiry alert for all gateways (Marek), move renewals to automation (Jun).
