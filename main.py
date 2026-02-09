import argparse
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
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

from observability.metrics import (
    start_metrics_server,
    bot_mode as m_bot_mode,
    exchange_connected as m_exchange_connected,
    ws_connected as m_ws_connected,
    api_latency_ms as m_api_latency_ms,
    last_tick_age_seconds as m_last_tick_age_seconds,
    current_price_usd as m_current_price_usd,
    equity_usd as m_equity_usd,
    pnl_total_usd as m_pnl_total_usd,
    pnl_daily_usd as m_pnl_daily_usd,
    drawdown_pct as m_drawdown_pct,
    fees_total_usd as m_fees_total_usd,
    capital_deployed_pct as m_capital_deployed_pct,
    open_orders_count as m_open_orders_count,
    failed_orders_count_1h as m_failed_orders_count_1h,
    reconciliation_ok as m_reconciliation_ok,
    volatility_regime as m_volatility_regime,
    volatility_confidence as m_volatility_confidence,
    trend_state as m_trend_state,
    trend_pause as m_trend_pause,
    rsi as m_rsi,
    adx as m_adx,
    atr as m_atr,
    grid_center_price as m_grid_center_price,
    grid_lower_bound as m_grid_lower_bound,
    grid_upper_bound as m_grid_upper_bound,
    grid_spacing as m_grid_spacing,
)

try:
    from data.db import ensure_schema, insert_trade_event, upsert_candles, upsert_indicator
except Exception:
    # DB optional; continue without DB if not available
    ensure_schema = None
    insert_trade_event = None
    upsert_candles = None
    upsert_indicator = None

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
        self._last_tick_ts: Optional[float] = None
        self._failed_order_ts: deque[float] = deque(maxlen=1000)
        self._last_regime: Optional[str] = None
        self._last_confidence: float = 0.0

        # Start Prometheus metrics server
        try:
            start_metrics_server(9000)
            m_bot_mode.labels(mode=self._mode).set(1)
        except Exception:
            logger.exception("Failed to start metrics server")

        # Ensure DB schema (optional)
        try:
            if ensure_schema:
                ensure_schema()
        except Exception:
            logger.warning("DB not available; continuing without DB")

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
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                }
                return json.dumps(payload)

        log_cfg = self._config.get("logging") or {}
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)

        root = logging.getLogger()
        root.setLevel(level)
        # stdout handler
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(JsonFormatter())
        root.addHandler(sh)
        # file handler (also JSON)
        try:
            os.makedirs("logs", exist_ok=True)
            fh = logging.FileHandler("logs/gridai.log")
            fh.setFormatter(JsonFormatter())
            root.addHandler(fh)
        except Exception:
            pass

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

        t0 = time.perf_counter()
        try:
            ticker = self._feed.fetch_ticker()
            m_exchange_connected.set(1)
        except Exception:
            m_exchange_connected.set(0)
            logger.exception("Failed to fetch ticker")
            return
        latency_ms = (time.perf_counter() - t0) * 1000.0
        m_api_latency_ms.set(latency_ms)

        price = ticker.get("last")
        if price is None:
            return
        m_current_price_usd.set(price)
        now = time.time()
        self._last_tick_ts = now
        m_last_tick_age_seconds.set(0)

        # Account metrics
        equity = self._position.current_capital + self._position.total_pnl()
        m_equity_usd.set(equity)
        m_pnl_total_usd.set(self._position.total_pnl())
        m_pnl_daily_usd.set(self._position.daily_pnl)
        m_drawdown_pct.set(self._position.drawdown_pct())
        m_fees_total_usd.set(self._position.total_fees)
        m_capital_deployed_pct.set(self._position.capital_deployed_pct())
        m_open_orders_count.set(len(self._order_mgr.get_open_orders()))
        # Prune failed order timestamps <=1h
        cutoff = now - 3600
        while self._failed_order_ts and self._failed_order_ts[0] < cutoff:
            self._failed_order_ts.popleft()
        m_failed_orders_count_1h.set(len(self._failed_order_ts))

        try:
            candles = self._feed.fetch_recent_ohlcv("5m", limit=200)
            if candles:
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            else:
                df = pd.DataFrame()
        except Exception:
            logger.warning("Failed to fetch candles")
            df = pd.DataFrame()

        if len(df) >= 50 and tick_count % 6 == 0:
            # Trend detection and indicators
            signal = self._trend.analyze(df)
            m_trend_pause.set(1 if signal.should_pause else 0)
            state_label = "trending" if signal.should_pause else "ranging"
            m_trend_state.labels(state=state_label).set(1)
            if signal.should_pause:
                self._grid.pause()
                logger.info("Grid paused: %s", signal.reason)
            elif self._grid.is_paused:
                self._grid.resume()

            # Indicators (via ta)
            try:
                from ta.momentum import RSIIndicator
                from ta.trend import MACD, EMAIndicator, ADXIndicator
                from ta.volatility import BollingerBands, AverageTrueRange

                close = df["close"]
                high = df["high"]
                low = df["low"]

                rsi_v = RSIIndicator(close, window=14).rsi().iloc[-1]
                macd_i = MACD(close, window_slow=26, window_fast=12, window_sign=9)
                macd_v = macd_i.macd().iloc[-1]
                macd_signal_v = macd_i.macd_signal().iloc[-1]
                bb = BollingerBands(close, window=20, window_dev=2)
                bb_u = bb.bollinger_hband().iloc[-1]
                bb_l = bb.bollinger_lband().iloc[-1]
                atr_v = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]
                adx_v = ADXIndicator(high, low, close, window=14).adx().iloc[-1]
                ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
                ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
                ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]

                m_rsi.set(float(rsi_v))
                m_atr.set(float(atr_v))
                m_adx.set(float(adx_v))

                if upsert_candles and upsert_indicator:
                    rows = list(zip(df["ts"].dt.tz_convert("UTC"), ["5m"]*len(df), df["open"], df["high"], df["low"], df["close"], df["volume"]))
                    try:
                        upsert_candles(rows[-50:])
                        upsert_indicator(df["ts"].iloc[-1].to_pydatetime(), float(ema20), float(ema50), float(ema200), float(rsi_v), float(macd_v), float(macd_signal_v), float(bb_u), float(bb_l), float(atr_v), float(adx_v))
                    except Exception:
                        logger.warning("DB write failed for candles/indicators")
            except Exception:
                logger.debug("Indicator calc failed", exc_info=True)

        if len(df) >= 50 and tick_count % 6 == 0:
            regime, confidence = self._volatility.predict(df)
            self._last_regime = regime.value
            self._last_confidence = float(confidence)
            m_volatility_confidence.set(float(confidence))
            for r in ("LOW", "MEDIUM", "HIGH"):
                m_volatility_regime.labels(regime=r.lower()).set(1 if r == regime.value else 0)
            if confidence >= self._confidence_threshold:
                mult = self._regime_multipliers.get(regime.value, 1.0)
                self._grid.set_regime_multiplier(mult)

        # Grid metrics
        if self._grid.state is not None:
            st = self._grid.state
            m_grid_center_price.set(st.center_price)
            m_grid_lower_bound.set(st.lower_bound)
            m_grid_upper_bound.set(st.upper_bound)
            m_grid_spacing.set(st.spacing)

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
            try:
                filled_ids = self._order_mgr.reconcile_orders()
                m_reconciliation_ok.set(1)
                for oid in filled_ids:
                    self._handle_fill(oid, price)
            except Exception:
                m_reconciliation_ok.set(0)
                logger.exception("Reconciliation failed")

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
                self._failed_order_ts.append(time.time())
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
        # Trade event to DB
        try:
            if insert_trade_event:
                insert_trade_event({
                    "ts": datetime.now(timezone.utc),
                    "trade_id": order_id,
                    "side": record.side,
                    "price": record.price,
                    "qty": record.amount,
                    "fee": fee,
                    "pnl": float(self._position.total_pnl()),
                    "regime": (self._last_regime or "unknown").lower(),
                    "confidence": float(self._last_confidence or 0.0),
                    "grid_level": filled_level.index if filled_level else None,
                })
        except Exception:
            logger.debug("trade_events insert failed", exc_info=True)

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
