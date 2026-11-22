# Data quality report: orders

Contract: orders 1.2.0

- row_count > 0: PASSED (14 rows)
- missing_count(quantity) = 0: FAILED, ORD-1011
- duplicate_count(order_id) = 0: FAILED, ORD-1007
- invalid_count(status) = 0: FAILED, ORD-1013
- min(unit_price) >= 0: FAILED, ORD-1014
