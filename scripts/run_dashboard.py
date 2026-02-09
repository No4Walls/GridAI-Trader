import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.config_manager import ConfigManager
from dashboard.app import run_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GridAI dashboard")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    config = ConfigManager(config_dir=args.config_dir, profile=args.profile)
    dash_cfg = config.get("dashboard") or {}

    host = args.host or dash_cfg.get("host", "0.0.0.0")
    port = args.port or dash_cfg.get("port", 8080)
    db_path = config.get("database", "path") or "state/gridai.db"

    run_dashboard(host=host, port=port, db_path=db_path)


if __name__ == "__main__":
    main()
