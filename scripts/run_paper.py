import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import GridAITrader


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GridAI in paper trading mode")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    trader = GridAITrader(mode="paper", profile=args.profile, config_dir=args.config_dir)
    trader.run()


if __name__ == "__main__":
    main()
