import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import ccxt

logger = logging.getLogger(__name__)


class RealtimeFeed:
    def __init__(
        self,
        exchange_id: str = "coinbase",
        trading_pair: str = "BTC/USDT",
        api_key: str = "",
        api_secret: str = "",
        sandbox: bool = False,
    ) -> None:
        config: Dict[str, Any] = {"enableRateLimit": True}
        if api_key:
            config["apiKey"] = api_key
        if api_secret:
            config["secret"] = api_secret
        if sandbox:
            config["sandbox"] = True

        self._exchange = getattr(ccxt, exchange_id)(config)
        self._trading_pair = trading_pair
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._last_price: Optional[float] = None
        self._last_ticker: Optional[Dict[str, Any]] = None

    @property
    def exchange(self) -> ccxt.Exchange:
        return self._exchange

    @property
    def last_price(self) -> Optional[float]:
        return self._last_price

    @property
    def last_ticker(self) -> Optional[Dict[str, Any]]:
        return self._last_ticker

    def on_tick(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._callbacks.append(callback)

    def fetch_ticker(self) -> Dict[str, Any]:
        ticker = self._exchange.fetch_ticker(self._trading_pair)
        self._last_ticker = ticker
        self._last_price = ticker.get("last")
        return ticker

    def fetch_order_book(self, limit: int = 20) -> Dict[str, Any]:
        return self._exchange.fetch_order_book(self._trading_pair, limit=limit)

    def fetch_recent_ohlcv(
        self, timeframe: str = "5m", limit: int = 100
    ) -> list:
        return self._exchange.fetch_ohlcv(
            self._trading_pair, timeframe=timeframe, limit=limit
        )

    def start_polling(self, interval: float = 10.0) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, args=(interval,), daemon=True
        )
        self._thread.start()
        logger.info("Realtime feed polling started (interval=%.1fs)", interval)

    def stop_polling(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=15)
            self._thread = None
        logger.info("Realtime feed polling stopped")

    def _poll_loop(self, interval: float) -> None:
        while self._running:
            try:
                ticker = self.fetch_ticker()
                for cb in self._callbacks:
                    try:
                        cb(ticker)
                    except Exception:
                        logger.exception("Error in tick callback")
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit exceeded, backing off")
                time.sleep(interval * 3)
            except ccxt.NetworkError as e:
                logger.warning("Network error: %s", e)
                time.sleep(interval * 2)
            except Exception:
                logger.exception("Unexpected error in poll loop")
                time.sleep(interval * 2)
            else:
                time.sleep(interval)

    def create_limit_buy(
        self, amount: float, price: float, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self._exchange.create_limit_buy_order(
            self._trading_pair, amount, price, params=params or {}
        )

    def create_limit_sell(
        self, amount: float, price: float, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self._exchange.create_limit_sell_order(
            self._trading_pair, amount, price, params=params or {}
        )

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._exchange.cancel_order(order_id, self._trading_pair)

    def fetch_order(self, order_id: str) -> Dict[str, Any]:
        return self._exchange.fetch_order(order_id, self._trading_pair)

    def fetch_open_orders(self) -> list:
        return self._exchange.fetch_open_orders(self._trading_pair)

    def fetch_balance(self) -> Dict[str, Any]:
        return self._exchange.fetch_balance()
