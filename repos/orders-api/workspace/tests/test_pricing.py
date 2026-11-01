from app.pricing import format_total, order_total
from app.settings import Settings

SETTINGS = Settings(
    bulk_threshold=10,
    bulk_discount_percent=15.0,
    max_discount_percent=20.0,
    tax_rate_percent=8.0,
    log_level="INFO",
)


def test_small_order_has_no_discount():
    assert order_total(2, 10.0, settings=SETTINGS) == 20.0


def test_bulk_discount_applies_at_threshold():
    assert order_total(10, 10.0, settings=SETTINGS) == 85.0


def test_format_total():
    assert format_total(12.5) == "USD 12.50"
