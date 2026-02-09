import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str
    buy_order_id: str
    sell_order_id: str
    buy_price: float
    sell_price: float
    amount: float
    profit_usdt: float
    fee_usdt: float
    net_profit_usdt: float
    timestamp: str


class PositionTracker:
    def __init__(self, db_path: str = "state/gridai.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._initial_capital: float = 0.0
        self._current_capital: float = 0.0
        self._peak_capital: float = 0.0
        self._btc_held: float = 0.0
        self._total_fees: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_reset_date: str = ""
        self._trade_count: int = 0

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    buy_order_id TEXT,
                    sell_order_id TEXT,
                    buy_price REAL,
                    sell_price REAL,
                    amount REAL,
                    profit_usdt REAL,
                    fee_usdt REAL,
                    net_profit_usdt REAL,
                    timestamp TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    equity_usdt REAL,
                    btc_held REAL,
                    btc_price REAL
                )
            """)
            conn.commit()

    def initialize(self, capital: float) -> None:
        self._initial_capital = capital
        self._current_capital = capital
        self._peak_capital = capital

    def record_buy(self, price: float, amount: float, fee: float = 0.0) -> None:
        with self._lock:
            cost = price * amount + fee
            self._current_capital -= cost
            self._btc_held += amount
            self._total_fees += fee
            logger.debug(
                "BUY: %.8f BTC @ %.2f, fee=%.4f, capital=%.2f",
                amount, price, fee, self._current_capital,
            )

    def record_sell(self, price: float, amount: float, fee: float = 0.0) -> None:
        with self._lock:
            revenue = price * amount - fee
            self._current_capital += revenue
            self._btc_held -= amount
            self._total_fees += fee
            if self._current_capital > self._peak_capital:
                self._peak_capital = self._current_capital
            logger.debug(
                "SELL: %.8f BTC @ %.2f, fee=%.4f, capital=%.2f",
                amount, price, fee, self._current_capital,
            )

    def record_completed_trade(
        self,
        buy_order_id: str,
        sell_order_id: str,
        buy_price: float,
        sell_price: float,
        amount: float,
        fee: float,
    ) -> TradeRecord:
        profit = (sell_price - buy_price) * amount
        net_profit = profit - fee
        trade_id = f"T-{self._trade_count + 1}"
        ts = datetime.now(timezone.utc).isoformat()

        record = TradeRecord(
            trade_id=trade_id,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            buy_price=buy_price,
            sell_price=sell_price,
            amount=amount,
            profit_usdt=profit,
            fee_usdt=fee,
            net_profit_usdt=net_profit,
            timestamp=ts,
        )

        with self._lock:
            self._trade_count += 1
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._daily_reset_date != today:
                self._daily_pnl = 0.0
                self._daily_reset_date = today
            self._daily_pnl += net_profit

        self._save_trade(record)
        logger.info(
            "Trade %s: buy=%.2f sell=%.2f amount=%.8f profit=%.4f net=%.4f",
            trade_id, buy_price, sell_price, amount, profit, net_profit,
        )
        return record

    def _save_trade(self, t: TradeRecord) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO trades
                    (trade_id, buy_order_id, sell_order_id, buy_price, sell_price,
                     amount, profit_usdt, fee_usdt, net_profit_usdt, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        t.trade_id, t.buy_order_id, t.sell_order_id,
                        t.buy_price, t.sell_price, t.amount,
                        t.profit_usdt, t.fee_usdt, t.net_profit_usdt, t.timestamp,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save trade %s", t.trade_id)

    def snapshot_equity(self, btc_price: float) -> float:
        equity = self._current_capital + self._btc_held * btc_price
        ts = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO equity_snapshots (timestamp, equity_usdt, btc_held, btc_price) VALUES (?, ?, ?, ?)",
                    (ts, equity, self._btc_held, btc_price),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save equity snapshot")
        return equity

    def get_equity_history(self, limit: int = 500) -> List[Dict[str, Any]]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT timestamp, equity_usdt, btc_held, btc_price FROM equity_snapshots ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"timestamp": r[0], "equity": r[1], "btc_held": r[2], "btc_price": r[3]}
                for r in reversed(rows)
            ]
        except Exception:
            logger.exception("Failed to load equity history")
            return []

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM trades ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "trade_id": r[0], "buy_order_id": r[1], "sell_order_id": r[2],
                    "buy_price": r[3], "sell_price": r[4], "amount": r[5],
                    "profit_usdt": r[6], "fee_usdt": r[7], "net_profit_usdt": r[8],
                    "timestamp": r[9],
                }
                for r in reversed(rows)
            ]
        except Exception:
            logger.exception("Failed to load recent trades")
            return []

    @property
    def current_capital(self) -> float:
        return self._current_capital

    @property
    def btc_held(self) -> float:
        return self._btc_held

    @property
    def total_fees(self) -> float:
        return self._total_fees

    @property
    def trade_count(self) -> int:
        return self._trade_count

    @property
    def daily_pnl(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
        return self._daily_pnl

    def drawdown_pct(self) -> float:
        if self._peak_capital <= 0:
            return 0.0
        return (self._peak_capital - self._current_capital) / self._peak_capital * 100

    def capital_deployed_pct(self) -> float:
        if self._initial_capital <= 0:
            return 0.0
        deployed = self._initial_capital - self._current_capital
        return max(0.0, deployed / self._initial_capital * 100)

    def total_pnl(self) -> float:
        return self._current_capital - self._initial_capital

    def save_state(self, extra: Optional[Dict[str, str]] = None) -> None:
        data = {
            "initial_capital": str(self._initial_capital),
            "current_capital": str(self._current_capital),
            "peak_capital": str(self._peak_capital),
            "btc_held": str(self._btc_held),
            "total_fees": str(self._total_fees),
            "trade_count": str(self._trade_count),
        }
        if extra:
            data.update(extra)
        try:
            with sqlite3.connect(self._db_path) as conn:
                for k, v in data.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                        (k, v),
                    )
                conn.commit()
        except Exception:
            logger.exception("Failed to save state")

    def load_state(self) -> bool:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute("SELECT key, value FROM state").fetchall()
            if not rows:
                return False
            state = dict(rows)
            self._initial_capital = float(state.get("initial_capital", 0))
            self._current_capital = float(state.get("current_capital", 0))
            self._peak_capital = float(state.get("peak_capital", 0))
            self._btc_held = float(state.get("btc_held", 0))
            self._total_fees = float(state.get("total_fees", 0))
            self._trade_count = int(state.get("trade_count", 0))
            logger.info("State restored: capital=%.2f, btc=%.8f", self._current_capital, self._btc_held)
            return True
        except Exception:
            logger.exception("Failed to load state")
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": self._initial_capital,
            "current_capital": self._current_capital,
            "peak_capital": self._peak_capital,
            "btc_held": self._btc_held,
            "total_fees": self._total_fees,
            "trade_count": self._trade_count,
            "total_pnl": self.total_pnl(),
            "drawdown_pct": self.drawdown_pct(),
            "capital_deployed_pct": self.capital_deployed_pct(),
            "daily_pnl": self.daily_pnl,
        }
