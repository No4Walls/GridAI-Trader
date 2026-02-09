import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GridSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class GridLevel:
    price: float
    side: GridSide
    index: int
    order_id: Optional[str] = None
    is_active: bool = False
    filled: bool = False


@dataclass
class GridState:
    levels: List[GridLevel] = field(default_factory=list)
    center_price: float = 0.0
    upper_bound: float = 0.0
    lower_bound: float = 0.0
    num_grids: int = 0
    spacing: float = 0.0
    regime_multiplier: float = 1.0


class GridEngine:
    def __init__(
        self,
        num_grids: int = 15,
        upper_bound_pct: float = 3.0,
        lower_bound_pct: float = 3.0,
        order_size_usdt: float = 50.0,
        max_open_orders: int = 30,
    ) -> None:
        self._num_grids = num_grids
        self._upper_bound_pct = upper_bound_pct
        self._lower_bound_pct = lower_bound_pct
        self._order_size_usdt = order_size_usdt
        self._max_open_orders = max_open_orders
        self._state: Optional[GridState] = None
        self._regime_multiplier: float = 1.0
        self._paused: bool = False

    @property
    def state(self) -> Optional[GridState]:
        return self._state

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True
        logger.info("Grid engine paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Grid engine resumed")

    def set_regime_multiplier(self, multiplier: float) -> None:
        self._regime_multiplier = max(0.1, min(5.0, multiplier))
        logger.info("Regime multiplier set to %.2f", self._regime_multiplier)

    def calculate_grid(self, current_price: float) -> GridState:
        effective_upper_pct = self._upper_bound_pct * self._regime_multiplier
        effective_lower_pct = self._lower_bound_pct * self._regime_multiplier

        upper_bound = current_price * (1 + effective_upper_pct / 100)
        lower_bound = current_price * (1 - effective_lower_pct / 100)

        total_range = upper_bound - lower_bound
        spacing = total_range / self._num_grids

        levels: List[GridLevel] = []
        for i in range(self._num_grids + 1):
            price = lower_bound + i * spacing
            price = round(price, 2)
            if price < current_price:
                side = GridSide.BUY
            elif price > current_price:
                side = GridSide.SELL
            else:
                continue
            levels.append(GridLevel(price=price, side=side, index=i))

        self._state = GridState(
            levels=levels,
            center_price=current_price,
            upper_bound=round(upper_bound, 2),
            lower_bound=round(lower_bound, 2),
            num_grids=self._num_grids,
            spacing=round(spacing, 2),
            regime_multiplier=self._regime_multiplier,
        )

        logger.info(
            "Grid calculated: center=%.2f, bounds=[%.2f, %.2f], spacing=%.2f, levels=%d",
            current_price,
            lower_bound,
            upper_bound,
            spacing,
            len(levels),
        )
        return self._state

    def get_orders_to_place(self) -> List[GridLevel]:
        if self._state is None or self._paused:
            return []

        active_count = sum(1 for l in self._state.levels if l.is_active)
        available_slots = self._max_open_orders - active_count

        pending = [
            l for l in self._state.levels if not l.is_active and not l.filled
        ]
        return pending[:available_slots]

    def mark_order_placed(self, index: int, order_id: str) -> None:
        if self._state is None:
            return
        for level in self._state.levels:
            if level.index == index:
                level.order_id = order_id
                level.is_active = True
                logger.debug("Order placed at grid %d: %s", index, order_id)
                return

    def mark_order_filled(self, order_id: str) -> Optional[GridLevel]:
        if self._state is None:
            return None
        for level in self._state.levels:
            if level.order_id == order_id:
                level.filled = True
                level.is_active = False
                logger.info(
                    "Grid level %d filled at %.2f (%s)",
                    level.index,
                    level.price,
                    level.side.value,
                )
                return level
        return None

    def mark_order_cancelled(self, order_id: str) -> None:
        if self._state is None:
            return
        for level in self._state.levels:
            if level.order_id == order_id:
                level.is_active = False
                level.order_id = None
                return

    def get_counter_order(self, filled_level: GridLevel) -> Optional[Dict[str, Any]]:
        if self._state is None:
            return None

        if filled_level.side == GridSide.BUY:
            counter_price = filled_level.price + self._state.spacing
            counter_side = GridSide.SELL
        else:
            counter_price = filled_level.price - self._state.spacing
            counter_side = GridSide.BUY

        if counter_price < self._state.lower_bound or counter_price > self._state.upper_bound:
            return None

        amount = self._order_size_usdt / counter_price
        return {
            "side": counter_side.value,
            "price": round(counter_price, 2),
            "amount": round(amount, 8),
            "source_index": filled_level.index,
        }

    def should_recalibrate(self, current_price: float, threshold_pct: float = 2.0) -> bool:
        if self._state is None:
            return True
        drift = abs(current_price - self._state.center_price) / self._state.center_price * 100
        return drift > threshold_pct

    def get_order_amount(self, price: float) -> float:
        return round(self._order_size_usdt / price, 8)

    def active_order_count(self) -> int:
        if self._state is None:
            return 0
        return sum(1 for l in self._state.levels if l.is_active)

    def to_dict(self) -> Dict[str, Any]:
        if self._state is None:
            return {}
        return {
            "center_price": self._state.center_price,
            "upper_bound": self._state.upper_bound,
            "lower_bound": self._state.lower_bound,
            "num_grids": self._state.num_grids,
            "spacing": self._state.spacing,
            "regime_multiplier": self._state.regime_multiplier,
            "paused": self._paused,
            "levels": [
                {
                    "index": l.index,
                    "price": l.price,
                    "side": l.side.value,
                    "order_id": l.order_id,
                    "is_active": l.is_active,
                    "filled": l.filled,
                }
                for l in self._state.levels
            ],
        }
