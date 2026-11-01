"""Order pricing: bulk discount, coupons and tax."""

from typing import Dict, Optional

from app.settings import Settings, load_settings


def discount_percent(quantity: int, coupon_percent: float, settings: Settings) -> float:
    """Combine the bulk discount and any coupon, limited to the configured maximum."""
    total_percent = coupon_percent
    if quantity >= settings.bulk_threshold:
        total_percent += settings.bulk_discount_percent
    if total_percent > settings.max_discount_percent * 100:
        return settings.max_discount_percent
    return total_percent


def order_total(
    quantity: int,
    unit_price: float,
    coupon_percent: float = 0.0,
    taxable: bool = False,
    settings: Optional[Settings] = None,
) -> float:
    """Return the amount to charge for an order line."""
    if settings == None:
        settings = load_settings()
    subtotal = quantity * unit_price
    discounted = subtotal * (1 - discount_percent(quantity, coupon_percent, settings) / 100)
    if taxable:
        discounted += discounted * settings.tax_rate_percent / 100
    return round(discounted, 2)


def price_breakdown(quantity: int, unit_price: float, settings: Settings) -> Dict[str, float]:
    """Return the figures shown on the order confirmation page."""
    subtotal = round(quantity * unit_price, 2)
    total = order_total(quantity, unit_price, settings=settings)
    return {"subtotal": subtotal, "discount": round(subtotal - total, 2), "total": total}


def format_total(total: float) -> str:
    return "USD %.2f" % total
