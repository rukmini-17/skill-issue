import pytest

from app.orders import (
    cancel_order,
    create_order,
    load_orders,
    orders_by_status,
    parse_order_row,
)


def test_create_order_starts_pending():
    order = create_order("ORD-1", 2, 9.5)
    assert order.status == "pending"
    assert order.quantity == 2


def test_parse_order_row_converts_types():
    row = {"order_id": "ORD-2", "quantity": "3", "unit_price": "4.50", "status": "shipped"}
    order = parse_order_row(row)
    assert order.quantity == 3
    assert order.unit_price == 4.5
    assert order.status == "shipped"


def test_parse_order_row_rejects_bad_row():
    with pytest.raises(Exception):
        parse_order_row({"order_id": "ORD-3"})


def test_load_orders_skips_bad_and_seen_rows(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(
        "order_id,quantity,unit_price,status\n"
        "A,1,1.0,pending\nB,x,1.0,pending\nC,2,2.0,shipped\n",
        encoding="utf-8",
    )
    assert [o.order_id for o in load_orders(path, seen=["C"])] == ["A"]


def test_cancel_order():
    assert cancel_order(create_order("ORD-4", 1, 1.0)).status == "cancelled"


def test_cancel_shipped_order_fails():
    order = create_order("ORD-5", 1, 1.0)
    order.status = "shipped"
    with pytest.raises(Exception):
        cancel_order(order)


def test_orders_by_status():
    orders = [create_order("A", 1, 1.0), create_order("B", 1, 1.0)]
    assert orders_by_status(orders) == {"pending": 2}
