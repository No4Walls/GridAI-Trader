import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grid_engine import GridEngine, GridSide, GridState


def test_calculate_grid_creates_levels():
    engine = GridEngine(num_grids=10, upper_bound_pct=2.0, lower_bound_pct=2.0, order_size_usdt=50.0)
    state = engine.calculate_grid(50000.0)
    assert state is not None
    assert state.num_grids == 10
    assert state.center_price == 50000.0
    assert len(state.levels) > 0
    assert state.upper_bound > state.center_price
    assert state.lower_bound < state.center_price


def test_grid_levels_have_correct_sides():
    engine = GridEngine(num_grids=10, upper_bound_pct=3.0, lower_bound_pct=3.0)
    state = engine.calculate_grid(50000.0)
    for level in state.levels:
        if level.price < 50000.0:
            assert level.side == GridSide.BUY
        elif level.price > 50000.0:
            assert level.side == GridSide.SELL


def test_grid_spacing():
    engine = GridEngine(num_grids=10, upper_bound_pct=5.0, lower_bound_pct=5.0)
    state = engine.calculate_grid(100000.0)
    assert state.spacing > 0
    expected_range = 100000.0 * 0.1
    assert abs((state.upper_bound - state.lower_bound) - expected_range) < 1.0


def test_mark_order_placed_and_filled():
    engine = GridEngine(num_grids=10)
    state = engine.calculate_grid(50000.0)
    first_level = state.levels[0]
    engine.mark_order_placed(first_level.index, "order-1")
    assert first_level.is_active
    assert first_level.order_id == "order-1"

    filled = engine.mark_order_filled("order-1")
    assert filled is not None
    assert filled.filled
    assert not filled.is_active


def test_counter_order():
    engine = GridEngine(num_grids=10, order_size_usdt=50.0)
    state = engine.calculate_grid(50000.0)
    buy_level = [l for l in state.levels if l.side == GridSide.BUY][0]
    buy_level.filled = True
    counter = engine.get_counter_order(buy_level)
    assert counter is not None
    assert counter["side"] == "sell"
    assert counter["price"] > buy_level.price


def test_should_recalibrate():
    engine = GridEngine(num_grids=10, upper_bound_pct=3.0, lower_bound_pct=3.0)
    engine.calculate_grid(50000.0)
    assert not engine.should_recalibrate(50000.0)
    assert not engine.should_recalibrate(50500.0)
    assert engine.should_recalibrate(52000.0)


def test_pause_resume():
    engine = GridEngine(num_grids=10)
    engine.calculate_grid(50000.0)
    engine.pause()
    assert engine.is_paused
    assert engine.get_orders_to_place() == []
    engine.resume()
    assert not engine.is_paused
    assert len(engine.get_orders_to_place()) > 0


def test_regime_multiplier():
    engine = GridEngine(num_grids=10, upper_bound_pct=3.0, lower_bound_pct=3.0)
    engine.set_regime_multiplier(2.0)
    state = engine.calculate_grid(50000.0)
    assert state.regime_multiplier == 2.0
    expected_upper = 50000.0 * (1 + 6.0 / 100)
    assert abs(state.upper_bound - expected_upper) < 1.0


def test_max_open_orders_respected():
    engine = GridEngine(num_grids=20, max_open_orders=5)
    engine.calculate_grid(50000.0)
    orders = engine.get_orders_to_place()
    assert len(orders) <= 5


def test_to_dict():
    engine = GridEngine(num_grids=10)
    engine.calculate_grid(50000.0)
    d = engine.to_dict()
    assert "center_price" in d
    assert "levels" in d
    assert len(d["levels"]) > 0


def test_active_order_count():
    engine = GridEngine(num_grids=10)
    state = engine.calculate_grid(50000.0)
    assert engine.active_order_count() == 0
    engine.mark_order_placed(state.levels[0].index, "o1")
    assert engine.active_order_count() == 1
