from app.pricing import order_total


def test_combined_discount_is_limited_to_the_configured_maximum():
    # 12 units at 10.00 with a 10% coupon: 25% combined, limited to 20%.
    assert order_total(12, 10.0, coupon_percent=10.0) == 96.0
