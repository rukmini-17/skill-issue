from app.orders import create_order, parse_order_row


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
