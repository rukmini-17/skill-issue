# Bug Reproduction Brief

- Target and commit: orders-api 0.4.0, app/pricing.py; commit unknown, the workspace is not a git repository
- Environment: local, Python and pytest versions from the commands below
- Expected: 12 units at 10.00 with a 10% coupon, not taxable, totals 96.00, because the combined discount is limited to max_discount_percent (20) in config/app.yaml
- Actual: the total is 90.00, a 25% discount
- Minimal steps: pytest reports/test_repro.py
- Minimal fixture: order_total(12, 10.0, coupon_percent=10.0)
- Reproduced: yes
- Evidence: two runs of pytest reports/test_repro.py both failed with assert 90.0 == 96.0
- Unknowns: whether production behaves the same way
- Safe next hypothesis to test: the maximum discount check in discount_percent never triggers. The report's rounding theory is unverified
