import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk.risk_manager import RiskAction, RiskManager


def test_ok_state():
    rm = RiskManager(
        max_drawdown_pct=15.0,
        max_capital_deployed_pct=50.0,
        daily_loss_cap_usdt=500.0,
        max_orders_per_day=200,
    )
    status = rm.evaluate(
        drawdown_pct=2.0,
        capital_deployed_pct=10.0,
        daily_pnl=50.0,
        daily_order_count=10,
        total_fees=5.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.OK
    assert not status.paused


def test_drawdown_pause():
    rm = RiskManager(max_drawdown_pct=15.0, emergency_stop_loss_pct=20.0)
    status = rm.evaluate(
        drawdown_pct=16.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.PAUSE
    assert rm.is_paused


def test_emergency_stop():
    rm = RiskManager(max_drawdown_pct=15.0, emergency_stop_loss_pct=20.0)
    status = rm.evaluate(
        drawdown_pct=25.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.EMERGENCY_STOP


def test_capital_deployed_pause():
    rm = RiskManager(max_capital_deployed_pct=50.0)
    status = rm.evaluate(
        drawdown_pct=0.0,
        capital_deployed_pct=55.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.PAUSE


def test_daily_loss_cap():
    rm = RiskManager(daily_loss_cap_usdt=500.0)
    status = rm.evaluate(
        drawdown_pct=0.0,
        capital_deployed_pct=10.0,
        daily_pnl=-600.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.PAUSE


def test_max_orders_per_day():
    rm = RiskManager(max_orders_per_day=100)
    status = rm.evaluate(
        drawdown_pct=0.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=150,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.PAUSE


def test_warn_state():
    rm = RiskManager(max_drawdown_pct=15.0, emergency_stop_loss_pct=20.0)
    status = rm.evaluate(
        drawdown_pct=13.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert status.overall_action == RiskAction.WARN


def test_can_place_order():
    rm = RiskManager()
    assert rm.can_place_order()
    rm.evaluate(
        drawdown_pct=20.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert not rm.can_place_order()


def test_reset_pause():
    rm = RiskManager(max_drawdown_pct=10.0)
    rm.evaluate(
        drawdown_pct=12.0,
        capital_deployed_pct=10.0,
        daily_pnl=0.0,
        daily_order_count=10,
        total_fees=0.0,
        initial_capital=10000.0,
    )
    assert rm.is_paused
    rm.reset_pause()
    assert not rm.is_paused


def test_to_dict():
    rm = RiskManager()
    rm.evaluate(
        drawdown_pct=5.0,
        capital_deployed_pct=20.0,
        daily_pnl=-100.0,
        daily_order_count=50,
        total_fees=10.0,
        initial_capital=10000.0,
    )
    d = rm.to_dict()
    assert "paused" in d
    assert "checks" in d
    assert len(d["checks"]) == 5
