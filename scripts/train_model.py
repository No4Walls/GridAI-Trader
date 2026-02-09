import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.volatility_classifier import VolatilityClassifier
from config.config_manager import ConfigManager
from data.historical_loader import HistoricalLoader

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train volatility classifier")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--data-file", default="", help="CSV file with OHLCV data")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2026-01-01")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--output", default="models/volatility_model.joblib")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted fetch from partial cache")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    config = ConfigManager(config_dir=args.config_dir, profile=args.profile)

    cache_path = "state/training_data.csv"
    Path("state").mkdir(parents=True, exist_ok=True)

    if args.data_file and Path(args.data_file).exists():
        logger.info("Loading data from %s", args.data_file)
        loader = HistoricalLoader()
        df = loader.load_from_csv(args.data_file)
    else:
        logger.info("Fetching historical data from exchange...")
        exchange_cfg = config.get("exchange") or {}
        loader = HistoricalLoader(
            exchange_id=exchange_cfg.get("name", "coinbase"),
            trading_pair=exchange_cfg.get("trading_pair", "BTC/USDT"),
        )
        resume_path = cache_path if args.resume else None
        df = loader.fetch_ohlcv(
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            resume_path=resume_path,
        )
        loader.save_to_csv(df, cache_path)
        logger.info("Data cached to %s (%d rows)", cache_path, len(df))

    logger.info("Training data: %d rows", len(df))

    if len(df) < 100:
        logger.error("Not enough data for training (need at least 100 rows, got %d)", len(df))
        sys.exit(1)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    classifier = VolatilityClassifier(model_path=args.output)
    results = classifier.train(df)

    logger.info("Training complete!")
    logger.info("Accuracy: %.4f", results["accuracy"])
    logger.info("Model saved to: %s", args.output)


if __name__ == "__main__":
    main()
