import argparse
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

import pandas as pd
from dotenv import load_dotenv

from ai.trend_detector import TrendDetector
from ai.volatility_classifier import VolatilityClassifier
from config.config_manager import ConfigManager
from core.grid_engine import GridEngine, GridSide
from core.order_manager import OrderManager
from core.position_tracker import PositionTracker
from data.realtime_feed import RealtimeFeed
from risk.risk_manager import RiskAction, RiskManager

logger = logging.getLogger(__name__)


class GridAITrader:
    def __init__(self, mode: str = "paper", profile: str = "default", config_dir: str = "config") -> None:
        load_dotenv()

        self._mode = mode
        self._config = ConfigManager(config_dir=config_dir, profile=profile)
        self._config.start_watching()
        self._setup_logging()
        self._running = False
        self._shutdown_requested = False

        logger.info("Initializing GridAI Trader (mode=%s, profile=%s)", mode, profile)

        grid_cfg = self._config.get("grid") or {}
        self._grid = GridEngine(
            num_grids=grid_cfg.get("num_grids", 15),
            upper_bound_pct=grid_cfg.get("upper_bound_pct", 3.0),
            lower_bound_pct=grid_cfg.get("lower_bound_pct", 3.0),
            order_size_usdt=grid_cfg.get("order_size_usdt", 50.0),
            max_open_orders=grid_cfg.get("max_open_orders", 30),
        )

        risk_cfg = self._config.get("risk") or {}
        self._risk = RiskManager(
            max_drawdown_pct=risk_cfg.get("max_drawdown_pct", 15.0),
            max_capital_deployed_pct=risk_cfg.get("max_capital_deployed_pct", 50.0),
            daily_loss_cap_usdt=risk_cfg.get("daily_loss_cap_usdt", 500.0),
            emergency_stop_loss_pct=risk_cfg.get("emergency_stop_loss_pct", 10.0),
            max_orders_per_day=risk_cfg.get("max_orders_per_day", 200),
            max_fee_pct=risk_cfg.get("max_fee_pct", 0.5),
            slippage_tolerance_pct=risk_cfg.get("slippage_tolerance_pct", 0.1),
        )

        trend_cfg = self._config.get("trend") or {}
        self._trend = TrendDetector(
            ma_fast_period=trend_cfg.get("ma_fast", 20),
            ma_slow_period=trend_cfg.get("ma_slow", 50),
            rsi_period=trend_cfg.get("rsi_period", 14),
            rsi_overbought=trend_cfg.get("rsi_overbought", 70),
            rsi_oversold=trend_cfg.get("rsi_oversold", 30),
            adx_period=trend_cfg.get("adx_period", 14),
            adx_strong_trend=trend_cfg.get("adx_strong_trend", 25),
            pause_on_strong_trend=trend_cfg.get("pause_on_strong_trend", True),
        )

        ai_cfg = self._config.get("ai") or {}
        self._volatility = VolatilityClassifier(
            model_path=ai_cfg.get("volatility_model_path", "models/volatility_model.joblib")
        )
        self._regime_multipliers = ai_cfg.get("regime_grid_multiplier", {
            "LOW": 0.7, "MEDIUM": 1.0, "HIGH": 1.5,
        })
        self._confidence_threshold = ai_cfg.get("confidence_threshold", 0.6)

        db_path = self._config.get("database", "path") or "state/gridai.db"
        self._position = PositionTracker(db_path=db_path)

        is_dry_run = mode == "paper"
        self._feed: Optional[RealtimeFeed] = None
        self._order_mgr: Optional[OrderManager] = None

        if mode in ("paper", "live"):
            exchange_cfg = self._config.get("exchange") or {}
            self._feed = RealtimeFeed(
                exchange_id=exchange_cfg.get("name", "coinbase"),
                trading_pair=exchange_cfg.get("trading_pair", "BTC/USDT"),
                api_key=os.environ.get("COINBASE_API_KEY", ""),
                api_secret=os.environ.get("COINBASE_API_SECRET", ""),
                sandbox=exchange_cfg.get("sandbox", False),
            )

            live_cfg = self._config.get("live") or {}
            if is_dry_run:
                self._order_mgr = OrderManager(
                    dry_run=True,
                    max_retries=live_cfg.get("retry_max_attempts", 5),
                    retry_backoff=live_cfg.get("retry_backoff_seconds", 2),
                    rate_limit_per_second=live_cfg.get("rate_limit_calls_per_second", 5),
                )
            else:
                self._order_mgr = OrderManager(
                    place_order_fn=None,
                    cancel_order_fn=self._feed.cancel_order,
                    fetch_order_fn=self._feed.fetch_order,
                    fetch_open_orders_fn=self._feed.fetch_open_orders,
                    dry_run=False,
                    max_retries=live_cfg.get("retry_max_attempts", 5),
                    retry_backoff=live_cfg.get("retry_backoff_seconds", 2),
                    rate_limit_per_second=live_cfg.get("rate_limit_calls_per_second", 5),
                )

        self._last_grid_calc: float = 0
        self._last_regime_check: float = 0
        self._last_trend_check: float = 0
        self._candle_buffer: list = []

    def _setup_logging(self) -> None:
        log_cfg = self._config.get("logging") or {}
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
        fmt = log_cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        logging.basicConfig(level=level, format=fmt, stream=sys.stdout)

    def _setup_live_order_fns(self) -> None:
        if self._feed is None or self._order_mgr is None:
            return
        if self._mode == "live":
            self._order_mgr._place_order_fn = None

    def get_state(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "position": self._position.to_dict(),
            "grid": self._grid.to_dict(),
            "volatility": self._volatility.to_dict(),
            "trend": self._trend.to_dict(),
            "risk": self._risk.to_dict(),
            "equity_history": self._position.get_equity_history(200),
            "trades": self._position.get_recent_trades(50),
        }

    def run(self) -> None:
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        if self._mode == "paper":
            paper_cfg = self._config.get("paper") or {}
            capital = paper_cfg.get("initial_capital_usdt", 10000.0)
        else:
            capital = 10000.0
        self._position.initialize(capital)

        if self._position.load_state():
            logger.info("Restored previous state")

        self._volatility.load_model()

        live_cfg = self._config.get("live") or {}
        poll_interval = live_cfg.get("poll_interval_seconds", 10)
        recalib_interval = self._config.get("grid", "recalibration_interval_minutes") or 60

        logger.info("GridAI Trader started (mode=%s)", self._mode)

        tick_count = 0
        while self._running and not self._shutdown_requested:
            try:
                self._tick(tick_count, recalib_interval)
                tick_count += 1
                time.sleep(poll_interval)
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Error in main loop")
                time.sleep(poll_interval * 2)

        self._shutdown()

    def _tick(self, tick_count: int, recalib_minutes: int) -> None:
        if self._feed is None or self._order_mgr is None:
            return

        try:
            ticker = self._feed.fetch_ticker()
        except Exception:
            logger.exception("Failed to fetch ticker")
            return

        price = ticker.get("last")
        if price is None:
            return

        try:
            candles = self._feed.fetch_recent_ohlcv("5m", limit=200)
            if candles:
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            else:
                df = pd.DataFrame()
        except Exception:
            logger.warning("Failed to fetch candles")
            df = pd.DataFrame()

        if len(df) >= 50 and tick_count % 6 == 0:
            signal = self._trend.analyze(df)
            if signal.should_pause:
                self._grid.pause()
                logger.info("Grid paused: %s", signal.reason)
            elif self._grid.is_paused:
                self._grid.resume()

        if len(df) >= 50 and tick_count % 6 == 0:
            regime, confidence = self._volatility.predict(df)
            if confidence >= self._confidence_threshold:
                mult = self._regime_multipliers.get(regime.value, 1.0)
                self._grid.set_regime_multiplier(mult)

        risk_status = self._risk.evaluate(
            drawdown_pct=self._position.drawdown_pct(),
            capital_deployed_pct=self._position.capital_deployed_pct(),
            daily_pnl=self._position.daily_pnl,
            daily_order_count=self._order_mgr.daily_order_count,
            total_fees=self._position.total_fees,
            initial_capital=self._position.current_capital + self._position.total_pnl(),
        )

        if risk_status.overall_action == RiskAction.EMERGENCY_STOP:
            logger.critical("EMERGENCY STOP triggered")
            self._order_mgr.cancel_all_open()
            self._position.save_state({"emergency_stop": "true"})
            self._running = False
            return

        if risk_status.overall_action == RiskAction.PAUSE:
            self._position.snapshot_equity(price)
            self._position.save_state()
            return

        if self._grid.state is None or self._grid.should_recalibrate(price):
            self._order_mgr.cancel_all_open()
            self._grid.calculate_grid(price)
            self._place_grid_orders(price)

        if tick_count % 6 == 0:
            filled_ids = self._order_mgr.reconcile_orders()
            for oid in filled_ids:
                self._handle_fill(oid, price)

        for record in self._order_mgr.get_open_orders():
            status = self._order_mgr.check_order_status(record.order_id)
            if status == "closed":
                self._handle_fill(record.order_id, price)

        self._position.snapshot_equity(price)
        self._position.save_state()

    def _place_grid_orders(self, current_price: float) -> None:
        if self._order_mgr is None:
            return
        orders = self._grid.get_orders_to_place()
        for level in orders:
            if not self._risk.can_place_order():
                break
            amount = self._grid.get_order_amount(level.price)
            try:
                record = self._order_mgr.place_order(
                    side=level.side.value,
                    price=level.price,
                    amount=amount,
                    grid_index=level.index,
                )
                self._grid.mark_order_placed(level.index, record.order_id)
                if level.side == GridSide.BUY:
                    pass
            except Exception:
                logger.exception("Failed to place order at grid %d", level.index)

    def _handle_fill(self, order_id: str, current_price: float) -> None:
        if self._order_mgr is None:
            return
        record = self._order_mgr.orders.get(order_id)
        if record is None:
            return

        filled_level = self._grid.mark_order_filled(order_id)
        fee = record.price * record.amount * 0.001

        if record.side == "buy":
            self._position.record_buy(record.price, record.amount, fee)
            counter = self._grid.get_counter_order(filled_level) if filled_level else None
            if counter and self._risk.can_place_order():
                try:
                    c_record = self._order_mgr.place_order(
                        side=counter["side"],
                        price=counter["price"],
                        amount=counter["amount"],
                        grid_index=counter["source_index"],
                    )
                    logger.info("Counter order placed: %s", c_record.order_id)
                except Exception:
                    logger.exception("Failed to place counter order")
        else:
            self._position.record_sell(record.price, record.amount, fee)
            self._position.record_completed_trade(
                buy_order_id="",
                sell_order_id=order_id,
                buy_price=record.price - (self._grid.state.spacing if self._grid.state else 0),
                sell_price=record.price,
                amount=record.amount,
                fee=fee,
            )

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("Signal %d received, shutting down...", signum)
        self._shutdown_requested = True
        self._running = False

    def _shutdown(self) -> None:
        logger.info("Shutting down GridAI Trader...")
        if self._order_mgr and self._mode == "paper":
            self._order_mgr.cancel_all_open()
        if self._feed:
            self._feed.stop_polling()
        self._position.save_state()
        self._config.stop_watching()
        logger.info("Shutdown complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="GridAI Trader")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    trader = GridAITrader(mode=args.mode, profile=args.profile, config_dir=args.config_dir)
    trader.run()


if __name__ == "__main__":
    main()
