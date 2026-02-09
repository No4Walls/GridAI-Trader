import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ai.volatility_classifier import VolatilityClassifier, VolatilityRegime
from ai.trend_detector import TrendDetector, TrendState
from backtesting.metrics import compute_all_metrics
from core.grid_engine import GridEngine, GridSide
from risk.risk_manager import RiskAction, RiskManager

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10000.0,
        fee_pct: float = 0.1,
        slippage_pct: float = 0.05,
        num_grids: int = 15,
        upper_bound_pct: float = 3.0,
        lower_bound_pct: float = 3.0,
        order_size_usdt: float = 50.0,
        max_open_orders: int = 30,
        use_ai: bool = True,
        regime_multipliers: Optional[Dict[str, float]] = None,
        risk_config: Optional[Dict[str, Any]] = None,
        trend_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._initial_capital = initial_capital
        self._fee_pct = fee_pct
        self._slippage_pct = slippage_pct
        self._use_ai = use_ai
        self._regime_multipliers = regime_multipliers or {
            "LOW": 0.7, "MEDIUM": 1.0, "HIGH": 1.5
        }

        self._grid = GridEngine(
            num_grids=num_grids,
            upper_bound_pct=upper_bound_pct,
            lower_bound_pct=lower_bound_pct,
            order_size_usdt=order_size_usdt,
            max_open_orders=max_open_orders,
        )

        risk_cfg = risk_config or {}
        self._risk = RiskManager(**risk_cfg)

        trend_cfg = trend_config or {}
        self._trend = TrendDetector(**trend_cfg)

        self._volatility = VolatilityClassifier()

        self._capital: float = initial_capital
        self._btc_held: float = 0.0
        self._peak_capital: float = initial_capital
        self._total_fees: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_order_count: int = 0
        self._last_day: str = ""

        self._equity_curve: List[float] = []
        self._trades: List[Dict[str, Any]] = []
        self._open_orders: List[Dict[str, Any]] = []

    def run(self, df: pd.DataFrame, recalib_every: int = 720) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(
            "Backtest starting: %d candles, capital=%.2f",
            len(df), self._initial_capital,
        )

        if self._use_ai:
            self._volatility.load_model()

        lookback = 100
        last_grid_price: Optional[float] = None
        last_regime_check = 0
        last_trend_check = 0
        paused = False

        for i in range(lookback, len(df)):
            row = df.iloc[i]
            price = float(row["close"])
            current_day = str(row["timestamp"])[:10] if "timestamp" in df.columns else ""

            if current_day != self._last_day:
                self._daily_pnl = 0.0
                self._daily_order_count = 0
                self._last_day = current_day

            if i - last_trend_check >= 12:
                window = df.iloc[max(0, i - lookback):i + 1]
                if len(window) >= 50:
                    signal = self._trend.analyze(window)
                    if signal.should_pause:
                        paused = True
                    else:
                        paused = False
                last_trend_check = i

            if self._use_ai and i - last_regime_check >= 12:
                window = df.iloc[max(0, i - 200):i + 1]
                if len(window) >= 50:
                    regime, confidence = self._volatility.predict(window)
                    mult = self._regime_multipliers.get(regime.value, 1.0)
                    self._grid.set_regime_multiplier(mult)
                last_regime_check = i

            risk_status = self._risk.evaluate(
                drawdown_pct=self._drawdown_pct(),
                capital_deployed_pct=self._capital_deployed_pct(),
                daily_pnl=self._daily_pnl,
                daily_order_count=self._daily_order_count,
                total_fees=self._total_fees,
                initial_capital=self._initial_capital,
            )

            if risk_status.overall_action in (RiskAction.PAUSE, RiskAction.EMERGENCY_STOP):
                equity = self._capital + self._btc_held * price
                self._equity_curve.append(equity)
                if risk_status.overall_action == RiskAction.EMERGENCY_STOP:
                    logger.warning("Emergency stop at candle %d", i)
                    break
                continue

            if paused:
                equity = self._capital + self._btc_held * price
                self._equity_curve.append(equity)
                continue

            if last_grid_price is None or (i % recalib_every == 0) or self._grid.should_recalibrate(price):
                self._cancel_all_sim_orders()
                self._grid.calculate_grid(price)
                last_grid_price = price
                self._place_grid_orders(price)

            self._check_fills(price, float(row.get("low", price)), float(row.get("high", price)))

            equity = self._capital + self._btc_held * price
            self._equity_curve.append(equity)
            if equity > self._peak_capital:
                self._peak_capital = equity

        elapsed = time.time() - start_time
        metrics = compute_all_metrics(
            self._equity_curve, self._trades, self._initial_capital
        )
        metrics["elapsed_seconds"] = round(elapsed, 2)
        metrics["candles_processed"] = len(df) - lookback

        logger.info("Backtest complete in %.2fs: %d trades", elapsed, len(self._trades))
        return metrics

    def _place_grid_orders(self, current_price: float) -> None:
        orders_to_place = self._grid.get_orders_to_place()
        for level in orders_to_place:
            amount = self._grid.get_order_amount(level.price)
            if level.side == GridSide.BUY:
                cost = level.price * amount
                if cost > self._capital:
                    continue
            self._open_orders.append({
                "index": level.index,
                "side": level.side.value,
                "price": level.price,
                "amount": amount,
            })
            self._grid.mark_order_placed(level.index, f"sim-{level.index}")
            self._daily_order_count += 1

    def _check_fills(self, close: float, low: float, high: float) -> None:
        filled = []
        for order in self._open_orders:
            if order["side"] == "buy" and low <= order["price"]:
                fill_price = order["price"] * (1 + self._slippage_pct / 100)
                fee = fill_price * order["amount"] * self._fee_pct / 100
                self._capital -= fill_price * order["amount"] + fee
                self._btc_held += order["amount"]
                self._total_fees += fee
                filled.append(order)
                self._grid.mark_order_filled(f"sim-{order['index']}")

                counter = self._grid.get_counter_order(
                    self._grid.state.levels[0].__class__(
                        price=order["price"],
                        side=GridSide.BUY,
                        index=order["index"],
                        filled=True,
                    )
                )
                if counter:
                    self._open_orders.append({
                        "index": order["index"] + 1000,
                        "side": counter["side"],
                        "price": counter["price"],
                        "amount": counter["amount"],
                    })

            elif order["side"] == "sell" and high >= order["price"]:
                fill_price = order["price"] * (1 - self._slippage_pct / 100)
                fee = fill_price * order["amount"] * self._fee_pct / 100
                revenue = fill_price * order["amount"] - fee
                self._capital += revenue
                self._btc_held -= order["amount"]
                self._total_fees += fee
                filled.append(order)

                profit = revenue - order["price"] * order["amount"]
                self._daily_pnl += profit
                self._trades.append({
                    "buy_price": order["price"] - self._grid.state.spacing if self._grid.state else order["price"],
                    "sell_price": fill_price,
                    "amount": order["amount"],
                    "profit_usdt": profit,
                    "fee_usdt": fee,
                    "net_profit_usdt": profit - fee,
                })

        for f in filled:
            self._open_orders.remove(f)

    def _cancel_all_sim_orders(self) -> None:
        self._open_orders.clear()

    def _drawdown_pct(self) -> float:
        if self._peak_capital <= 0:
            return 0.0
        return (self._peak_capital - self._capital) / self._peak_capital * 100

    def _capital_deployed_pct(self) -> float:
        if self._initial_capital <= 0:
            return 0.0
        deployed = self._initial_capital - self._capital
        return max(0.0, deployed / self._initial_capital * 100)

    @property
    def equity_curve(self) -> List[float]:
        return self._equity_curve

    @property
    def trades(self) -> List[Dict[str, Any]]:
        return self._trades
