import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.order_manager import OrderManager


def test_dry_run_place_order():
    mgr = OrderManager(dry_run=True)
    record = mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    assert record.order_id.startswith("dry-")
    assert record.status == "open"
    assert record.side == "buy"
    assert record.price == 50000.0


def test_dry_run_cancel_order():
    mgr = OrderManager(dry_run=True)
    record = mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    result = mgr.cancel_order(record.order_id)
    assert result
    assert mgr.orders[record.order_id].status == "cancelled"


def test_get_open_orders():
    mgr = OrderManager(dry_run=True)
    mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    mgr.place_order(side="sell", price=51000.0, amount=0.001, grid_index=1)
    assert len(mgr.get_open_orders()) == 2


def test_cancel_all_open():
    mgr = OrderManager(dry_run=True)
    for i in range(5):
        mgr.place_order(side="buy", price=50000.0 - i * 100, amount=0.001, grid_index=i)
    cancelled = mgr.cancel_all_open()
    assert cancelled == 5
    assert len(mgr.get_open_orders()) == 0


def test_daily_order_count():
    mgr = OrderManager(dry_run=True)
    for i in range(10):
        mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=i)
    assert mgr.daily_order_count == 10


def test_to_dict_list():
    mgr = OrderManager(dry_run=True)
    mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    dl = mgr.to_dict_list()
    assert len(dl) == 1
    assert dl[0]["side"] == "buy"
    assert dl[0]["price"] == 50000.0


def test_check_order_status_dry_run():
    mgr = OrderManager(dry_run=True)
    record = mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    status = mgr.check_order_status(record.order_id)
    assert status == "open"


def test_total_fees():
    mgr = OrderManager(dry_run=True)
    mgr.place_order(side="buy", price=50000.0, amount=0.001, grid_index=0)
    assert mgr.total_fees() == 0.0
