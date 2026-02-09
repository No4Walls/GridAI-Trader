import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from jsonschema import ValidationError, validate
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "exchange": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "trading_pair": {"type": "string"},
                "sandbox": {"type": "boolean"},
            },
            "required": ["name", "trading_pair"],
        },
        "grid": {
            "type": "object",
            "properties": {
                "num_grids": {"type": "integer", "minimum": 2, "maximum": 100},
                "upper_bound_pct": {"type": "number", "minimum": 0.1},
                "lower_bound_pct": {"type": "number", "minimum": 0.1},
                "order_size_usdt": {"type": "number", "minimum": 1.0},
                "recalibration_interval_minutes": {"type": "integer", "minimum": 1},
                "max_open_orders": {"type": "integer", "minimum": 1},
            },
            "required": ["num_grids", "upper_bound_pct", "lower_bound_pct", "order_size_usdt"],
        },
        "risk": {
            "type": "object",
            "properties": {
                "max_drawdown_pct": {"type": "number", "minimum": 0.1, "maximum": 100},
                "max_capital_deployed_pct": {"type": "number", "minimum": 0.1, "maximum": 100},
                "daily_loss_cap_usdt": {"type": "number", "minimum": 0},
                "emergency_stop_loss_pct": {"type": "number", "minimum": 0.1},
                "max_orders_per_day": {"type": "integer", "minimum": 1},
                "max_fee_pct": {"type": "number", "minimum": 0},
                "slippage_tolerance_pct": {"type": "number", "minimum": 0},
            },
            "required": ["max_drawdown_pct", "max_capital_deployed_pct"],
        },
    },
    "required": ["exchange", "grid", "risk"],
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigReloadHandler(FileSystemEventHandler):
    def __init__(self, config_manager: "ConfigManager") -> None:
        self._config_manager = config_manager

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        if event.src_path.endswith(".yaml") or event.src_path.endswith(".yml"):
            logger.info("Config file changed: %s — reloading", event.src_path)
            try:
                self._config_manager.reload()
            except Exception:
                logger.exception("Failed to reload config after file change")


class ConfigManager:
    def __init__(
        self,
        config_dir: str = "config",
        profile: str = "default",
        override_file: Optional[str] = None,
    ) -> None:
        self._config_dir = Path(config_dir)
        self._profile = profile
        self._override_file = override_file
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._observer: Optional[Observer] = None
        self.reload()

    def reload(self) -> None:
        with self._lock:
            default_path = self._config_dir / "default.yaml"
            if not default_path.exists():
                raise FileNotFoundError(f"Default config not found: {default_path}")

            with open(default_path) as f:
                base = yaml.safe_load(f) or {}

            if self._profile != "default":
                profile_path = self._config_dir / f"{self._profile}.yaml"
                if profile_path.exists():
                    with open(profile_path) as f:
                        profile_cfg = yaml.safe_load(f) or {}
                    base = deep_merge(base, profile_cfg)
                else:
                    logger.warning("Profile config not found: %s", profile_path)

            if self._override_file:
                override_path = Path(self._override_file)
                if override_path.exists():
                    with open(override_path) as f:
                        override_cfg = yaml.safe_load(f) or {}
                    base = deep_merge(base, override_cfg)

            self._apply_env_overrides(base)

            try:
                validate(instance=base, schema=CONFIG_SCHEMA)
            except ValidationError as e:
                logger.error("Config validation failed: %s", e.message)
                raise

            self._config = base
            logger.info("Config loaded (profile=%s)", self._profile)

    def _apply_env_overrides(self, cfg: Dict[str, Any]) -> None:
        env_map = {
            "GRIDAI_NUM_GRIDS": ("grid", "num_grids", int),
            "GRIDAI_ORDER_SIZE": ("grid", "order_size_usdt", float),
            "GRIDAI_MAX_DRAWDOWN": ("risk", "max_drawdown_pct", float),
            "GRIDAI_MAX_CAPITAL": ("risk", "max_capital_deployed_pct", float),
            "GRIDAI_DAILY_LOSS_CAP": ("risk", "daily_loss_cap_usdt", float),
            "GRIDAI_LOG_LEVEL": ("logging", "level", str),
        }
        for env_key, (section, key, typ) in env_map.items():
            val = os.environ.get(env_key)
            if val is not None:
                if section not in cfg:
                    cfg[section] = {}
                cfg[section][key] = typ(val)

    def get(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            obj = self._config
            for k in keys:
                if isinstance(obj, dict) and k in obj:
                    obj = obj[k]
                else:
                    return default
            return copy.deepcopy(obj)

    @property
    def config(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config)

    def start_watching(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        handler = ConfigReloadHandler(self)
        self._observer.schedule(handler, str(self._config_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("Config watcher started on %s", self._config_dir)

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
