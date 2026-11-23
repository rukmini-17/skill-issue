# ADR input: billing retry strategy

Date: 2026-10-08. Stakeholders: Jun Tanaka (Billing), Marek Lindqvist (Platform), Anna Varga (Finance).

Context: the September outage came from unbounded retries against the tax service. Invoices have to reach clients within four hours.

Decision: capped exponential backoff, at most 5 attempts, then move the invoice to a dead-letter queue that finance reviews each morning.

Alternatives:
- Fixed-interval retries: simpler, rejected because they keep hammering a struggling service.
- Circuit breaker only: rejected for now because it needs a shared state store we do not run.

Trade-offs: the dead-letter queue adds a daily manual step for finance. Invoices can wait until the morning review.
