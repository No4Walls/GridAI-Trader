import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import GridAITrader

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GridAI in LIVE trading mode")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    api_key = os.environ.get("COINBASE_API_KEY", "")
    api_secret = os.environ.get("COINBASE_API_SECRET", "")

    if not api_key or not api_secret:
        logger.error("COINBASE_API_KEY and COINBASE_API_SECRET must be set")
        sys.exit(1)

    logger.warning("=" * 60)
    logger.warning("  LIVE TRADING MODE — REAL MONEY AT RISK")
    logger.warning("  Ensure risk parameters are properly configured")
    logger.warning("=" * 60)

    trader = GridAITrader(mode="live", profile=args.profile, config_dir=args.config_dir)
    trader.run()


if __name__ == "__main__":
    main()
