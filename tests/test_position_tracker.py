import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.position_tracker import PositionTracker


def _make_tracker() -> PositionTracker:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tracker = PositionTracker(db_path=path)
    tracker.initialize(10000.0)
    return tracker


def test_initialize():
    t = _make_tracker()
    assert t.current_capital == 10000.0
    assert t.btc_held == 0.0
    assert t.trade_count == 0


def test_record_buy():
    t = _make_tracker()
    t.record_buy(price=50000.0, amount=0.01, fee=0.5)
    assert t.current_capital < 10000.0
    assert t.btc_held == 0.01
    assert t.total_fees == 0.5


def test_record_sell():
    t = _make_tracker()
    t.record_buy(price=50000.0, amount=0.01, fee=0.5)
    t.record_sell(price=51000.0, amount=0.01, fee=0.5)
    assert t.btc_held == 0.0
    assert t.total_fees == 1.0


def test_completed_trade():
    t = _make_tracker()
    t.record_buy(price=50000.0, amount=0.01, fee=0.5)
    record = t.record_completed_trade(
        buy_order_id="b1",
        sell_order_id="s1",
        buy_price=50000.0,
        sell_price=51000.0,
        amount=0.01,
        fee=1.0,
    )
    assert record.net_profit_usdt > 0
    assert t.trade_count == 1


def test_drawdown_pct():
    t = _make_tracker()
    t.record_buy(price=50000.0, amount=0.1, fee=0.0)
    dd = t.drawdown_pct()
    assert dd > 0


def test_save_and_load_state():
    t = _make_tracker()
    t.record_buy(price=50000.0, amount=0.01, fee=0.5)
    t.save_state()

    t2 = PositionTracker(db_path=t._db_path)
    assert t2.load_state()
    assert abs(t2.current_capital - t.current_capital) < 0.01
    assert abs(t2.btc_held - t.btc_held) < 0.000001


def test_equity_snapshot():
    t = _make_tracker()
    equity = t.snapshot_equity(50000.0)
    assert equity == 10000.0
    history = t.get_equity_history()
    assert len(history) == 1


def test_to_dict():
    t = _make_tracker()
    d = t.to_dict()
    assert d["initial_capital"] == 10000.0
    assert "total_pnl" in d
    assert "drawdown_pct" in d
