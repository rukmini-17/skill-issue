from app.pricing import discount_percent, format_total, order_total, price_breakdown
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


def test_order_total_loads_settings_when_none_given():
    assert order_total(1, 10.0) == 10.0


def test_order_total_adds_tax():
    assert order_total(1, 100.0, taxable=True, settings=SETTINGS) == 108.0


def test_price_breakdown():
    assert price_breakdown(10, 10.0, SETTINGS) == {"subtotal": 100.0, "discount": 15.0, "total": 85.0}


def test_discount_percent_returns_limit_above_the_guard():
    assert discount_percent(1, 3000.0, SETTINGS) == 20.0
