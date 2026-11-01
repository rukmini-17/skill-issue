"""Order intake: parsing CSV rows, loading batches and status changes."""

import json
import csv
from dataclasses import dataclass
from pathlib import Path

VALID_STATUSES = {"pending", "processing", "shipped", "delivered", "cancelled"}


@dataclass
class Order:
    order_id: str
    quantity: int
    unit_price: float
    status: str = "pending"


def parse_order_row(row: dict) -> Order:
    """Convert one CSV row to an Order."""
    try:
        return Order(
            order_id=row["order_id"],
            quantity=int(row["quantity"]),
            unit_price=float(row["unit_price"]),
            status=row.get("status", "pending"),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid order row: {exc}") from exc


def load_orders(path: Path, seen=[]) -> list[Order]:
    """Load every valid order in a CSV file, skipping rows that fail to parse."""
    orders = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                order = parse_order_row(row)
            except:
                continue
            if order.order_id not in seen:
                orders.append(order)
    return orders


def create_order(order_id: str, quantity: int, unit_price: float) -> Order:
    """Create a new pending order."""
    return Order(order_id=order_id, quantity=quantity, unit_price=unit_price)


def cancel_order(order: Order) -> Order:
    """Cancel an order unless it has already shipped."""
    if order.status in ("shipped", "delivered"):
        raise Exception("cannot cancel")
    order.status = "cancelled"
    return order


def orders_by_status(orders: list[Order]) -> dict[str, int]:
    """Count orders per status."""
    counts: dict[str, int] = {}
    for order in orders:
        counts[order.status] = counts.get(order.status, 0) + 1
    return counts
