import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RiskAction(str, Enum):
    OK = "OK"
    WARN = "WARN"
    PAUSE = "PAUSE"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass
class RiskCheck:
    name: str
    action: RiskAction
    value: float
    threshold: float
    message: str


@dataclass
class RiskStatus:
    overall_action: RiskAction
    checks: List[RiskCheck] = field(default_factory=list)
    paused: bool = False
    pause_reason: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RiskManager:
    def __init__(
        self,
        max_drawdown_pct: float = 15.0,
        max_capital_deployed_pct: float = 50.0,
        daily_loss_cap_usdt: float = 500.0,
        emergency_stop_loss_pct: float = 10.0,
        max_orders_per_day: int = 200,
        max_fee_pct: float = 0.5,
        slippage_tolerance_pct: float = 0.1,
    ) -> None:
        self._max_drawdown_pct = max_drawdown_pct
        self._max_capital_deployed_pct = max_capital_deployed_pct
        self._daily_loss_cap_usdt = daily_loss_cap_usdt
        self._emergency_stop_loss_pct = emergency_stop_loss_pct
        self._max_orders_per_day = max_orders_per_day
        self._max_fee_pct = max_fee_pct
        self._slippage_tolerance_pct = slippage_tolerance_pct
        self._paused = False
        self._pause_reason = ""
        self._last_status: Optional[RiskStatus] = None

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def evaluate(
        self,
        drawdown_pct: float,
        capital_deployed_pct: float,
        daily_pnl: float,
        daily_order_count: int,
        total_fees: float,
        initial_capital: float,
    ) -> RiskStatus:
        checks: List[RiskCheck] = []
        worst_action = RiskAction.OK

        dd_check = self._check_drawdown(drawdown_pct)
        checks.append(dd_check)
        worst_action = self._escalate(worst_action, dd_check.action)

        cap_check = self._check_capital_deployed(capital_deployed_pct)
        checks.append(cap_check)
        worst_action = self._escalate(worst_action, cap_check.action)

        loss_check = self._check_daily_loss(daily_pnl)
        checks.append(loss_check)
        worst_action = self._escalate(worst_action, loss_check.action)

        order_check = self._check_order_count(daily_order_count)
        checks.append(order_check)
        worst_action = self._escalate(worst_action, order_check.action)

        fee_check = self._check_fees(total_fees, initial_capital)
        checks.append(fee_check)
        worst_action = self._escalate(worst_action, fee_check.action)

        if worst_action in (RiskAction.PAUSE, RiskAction.EMERGENCY_STOP):
            breached = [c for c in checks if c.action in (RiskAction.PAUSE, RiskAction.EMERGENCY_STOP)]
            self._paused = True
            self._pause_reason = "; ".join(c.message for c in breached)
            logger.warning("RISK BREACH: %s", self._pause_reason)
        elif worst_action == RiskAction.OK and self._paused:
            pass

        status = RiskStatus(
            overall_action=worst_action,
            checks=checks,
            paused=self._paused,
            pause_reason=self._pause_reason,
        )
        self._last_status = status
        return status

    def reset_pause(self) -> None:
        self._paused = False
        self._pause_reason = ""
        logger.info("Risk pause reset manually")

    def _check_drawdown(self, drawdown_pct: float) -> RiskCheck:
        if drawdown_pct >= self._emergency_stop_loss_pct:
            return RiskCheck(
                name="drawdown",
                action=RiskAction.EMERGENCY_STOP,
                value=drawdown_pct,
                threshold=self._emergency_stop_loss_pct,
                message=f"EMERGENCY: Drawdown {drawdown_pct:.1f}% >= {self._emergency_stop_loss_pct:.1f}%",
            )
        if drawdown_pct >= self._max_drawdown_pct:
            return RiskCheck(
                name="drawdown",
                action=RiskAction.PAUSE,
                value=drawdown_pct,
                threshold=self._max_drawdown_pct,
                message=f"Drawdown {drawdown_pct:.1f}% >= {self._max_drawdown_pct:.1f}%",
            )
        if drawdown_pct >= self._max_drawdown_pct * 0.8:
            return RiskCheck(
                name="drawdown",
                action=RiskAction.WARN,
                value=drawdown_pct,
                threshold=self._max_drawdown_pct,
                message=f"Drawdown approaching limit: {drawdown_pct:.1f}%",
            )
        return RiskCheck(
            name="drawdown",
            action=RiskAction.OK,
            value=drawdown_pct,
            threshold=self._max_drawdown_pct,
            message="OK",
        )

    def _check_capital_deployed(self, deployed_pct: float) -> RiskCheck:
        if deployed_pct >= self._max_capital_deployed_pct:
            return RiskCheck(
                name="capital_deployed",
                action=RiskAction.PAUSE,
                value=deployed_pct,
                threshold=self._max_capital_deployed_pct,
                message=f"Capital deployed {deployed_pct:.1f}% >= {self._max_capital_deployed_pct:.1f}%",
            )
        if deployed_pct >= self._max_capital_deployed_pct * 0.8:
            return RiskCheck(
                name="capital_deployed",
                action=RiskAction.WARN,
                value=deployed_pct,
                threshold=self._max_capital_deployed_pct,
                message=f"Capital deployed approaching limit: {deployed_pct:.1f}%",
            )
        return RiskCheck(
            name="capital_deployed",
            action=RiskAction.OK,
            value=deployed_pct,
            threshold=self._max_capital_deployed_pct,
            message="OK",
        )

    def _check_daily_loss(self, daily_pnl: float) -> RiskCheck:
        if daily_pnl <= -self._daily_loss_cap_usdt:
            return RiskCheck(
                name="daily_loss",
                action=RiskAction.PAUSE,
                value=abs(daily_pnl),
                threshold=self._daily_loss_cap_usdt,
                message=f"Daily loss ${abs(daily_pnl):.2f} >= cap ${self._daily_loss_cap_usdt:.2f}",
            )
        return RiskCheck(
            name="daily_loss",
            action=RiskAction.OK,
            value=abs(daily_pnl),
            threshold=self._daily_loss_cap_usdt,
            message="OK",
        )

    def _check_order_count(self, count: int) -> RiskCheck:
        if count >= self._max_orders_per_day:
            return RiskCheck(
                name="order_count",
                action=RiskAction.PAUSE,
                value=float(count),
                threshold=float(self._max_orders_per_day),
                message=f"Daily orders {count} >= {self._max_orders_per_day}",
            )
        return RiskCheck(
            name="order_count",
            action=RiskAction.OK,
            value=float(count),
            threshold=float(self._max_orders_per_day),
            message="OK",
        )

    def _check_fees(self, total_fees: float, initial_capital: float) -> RiskCheck:
        if initial_capital <= 0:
            return RiskCheck(
                name="fees", action=RiskAction.OK, value=0, threshold=0, message="OK"
            )
        fee_pct = total_fees / initial_capital * 100
        if fee_pct >= self._max_fee_pct:
            return RiskCheck(
                name="fees",
                action=RiskAction.WARN,
                value=fee_pct,
                threshold=self._max_fee_pct,
                message=f"Total fees {fee_pct:.2f}% of capital",
            )
        return RiskCheck(
            name="fees",
            action=RiskAction.OK,
            value=fee_pct,
            threshold=self._max_fee_pct,
            message="OK",
        )

    def _escalate(self, current: RiskAction, new: RiskAction) -> RiskAction:
        priority = {
            RiskAction.OK: 0,
            RiskAction.WARN: 1,
            RiskAction.PAUSE: 2,
            RiskAction.EMERGENCY_STOP: 3,
        }
        return new if priority[new] > priority[current] else current

    def can_place_order(self) -> bool:
        return not self._paused

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "paused": self._paused,
            "pause_reason": self._pause_reason,
        }
        if self._last_status:
            result["overall_action"] = self._last_status.overall_action.value
            result["checks"] = [
                {
                    "name": c.name,
                    "action": c.action.value,
                    "value": c.value,
                    "threshold": c.threshold,
                    "message": c.message,
                }
                for c in self._last_status.checks
            ]
        return result
