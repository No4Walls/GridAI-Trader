import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.backtest_engine import BacktestEngine
from config.config_manager import ConfigManager
from data.historical_loader import HistoricalLoader

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GridAI backtest")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--data-file", default="", help="CSV file with OHLCV data")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--output", default="state/backtest_results.json")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    config = ConfigManager(config_dir=args.config_dir, profile=args.profile)
    bt_cfg = config.get("backtesting") or {}
    grid_cfg = config.get("grid") or {}
    risk_cfg = config.get("risk") or {}
    trend_cfg = config.get("trend") or {}
    ai_cfg = config.get("ai") or {}

    start_date = args.start_date or bt_cfg.get("start_date", "2024-01-01")
    end_date = args.end_date or bt_cfg.get("end_date", "2026-01-01")

    if args.data_file and Path(args.data_file).exists():
        logger.info("Loading data from %s", args.data_file)
        loader = HistoricalLoader()
        df = loader.load_from_csv(args.data_file)
    else:
        logger.info("Fetching historical data...")
        exchange_cfg = config.get("exchange") or {}
        loader = HistoricalLoader(
            exchange_id=exchange_cfg.get("name", "coinbase"),
            trading_pair=exchange_cfg.get("trading_pair", "BTC/USDT"),
        )
        df = loader.fetch_ohlcv(timeframe="5m", start_date=start_date, end_date=end_date)
        cache_path = "state/backtest_data.csv"
        Path("state").mkdir(parents=True, exist_ok=True)
        loader.save_to_csv(df, cache_path)

    logger.info("Backtest data: %d candles", len(df))

    regime_mult = ai_cfg.get("regime_grid_multiplier", {"LOW": 0.7, "MEDIUM": 1.0, "HIGH": 1.5})

    engine = BacktestEngine(
        initial_capital=bt_cfg.get("initial_capital_usdt", 10000.0),
        fee_pct=bt_cfg.get("fee_pct", 0.1),
        slippage_pct=bt_cfg.get("slippage_pct", 0.05),
        num_grids=grid_cfg.get("num_grids", 15),
        upper_bound_pct=grid_cfg.get("upper_bound_pct", 3.0),
        lower_bound_pct=grid_cfg.get("lower_bound_pct", 3.0),
        order_size_usdt=grid_cfg.get("order_size_usdt", 50.0),
        max_open_orders=grid_cfg.get("max_open_orders", 30),
        use_ai=True,
        regime_multipliers=regime_mult,
        risk_config={
            "max_drawdown_pct": risk_cfg.get("max_drawdown_pct", 15.0),
            "max_capital_deployed_pct": risk_cfg.get("max_capital_deployed_pct", 50.0),
            "daily_loss_cap_usdt": risk_cfg.get("daily_loss_cap_usdt", 500.0),
            "emergency_stop_loss_pct": risk_cfg.get("emergency_stop_loss_pct", 10.0),
            "max_orders_per_day": risk_cfg.get("max_orders_per_day", 200),
        },
        trend_config={
            "ma_fast_period": trend_cfg.get("ma_fast", 20),
            "ma_slow_period": trend_cfg.get("ma_slow", 50),
            "rsi_period": trend_cfg.get("rsi_period", 14),
            "adx_period": trend_cfg.get("adx_period", 14),
            "adx_strong_trend": trend_cfg.get("adx_strong_trend", 25),
            "pause_on_strong_trend": trend_cfg.get("pause_on_strong_trend", True),
        },
    )

    results = engine.run(df)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("=" * 60)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 60)
    for key, val in results.items():
        logger.info("  %-25s: %s", key, val)
    logger.info("=" * 60)
    logger.info("Results saved to: %s", args.output)


if __name__ == "__main__":
    main()
