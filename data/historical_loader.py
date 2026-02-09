import logging
import time
from datetime import datetime, timezone
from typing import Optional

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)


class HistoricalLoader:
    def __init__(
        self,
        exchange_id: str = "coinbase",
        trading_pair: str = "BTC/USDT",
    ) -> None:
        self._exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self._trading_pair = trading_pair

    def fetch_ohlcv(
        self,
        timeframe: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit_per_request: int = 300,
    ) -> pd.DataFrame:
        if start_date:
            since = int(
                datetime.strptime(start_date, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
                * 1000
            )
        else:
            since = int(
                datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
            )

        if end_date:
            end_ts = int(
                datetime.strptime(end_date, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
                * 1000
            )
        else:
            end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

        all_candles = []
        current_since = since

        while current_since < end_ts:
            try:
                candles = self._exchange.fetch_ohlcv(
                    self._trading_pair,
                    timeframe=timeframe,
                    since=current_since,
                    limit=limit_per_request,
                )
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit hit, sleeping 10s")
                time.sleep(10)
                continue
            except ccxt.BaseError as e:
                logger.error("Exchange error fetching OHLCV: %s", e)
                raise

            if not candles:
                break

            all_candles.extend(candles)
            last_ts = candles[-1][0]
            if last_ts <= current_since:
                break
            current_since = last_ts + 1

            time.sleep(self._exchange.rateLimit / 1000)

        if not all_candles:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df[df["timestamp"] <= pd.Timestamp(end_ts, unit="ms", tz="UTC")]
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df

    def load_from_csv(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def save_to_csv(self, df: pd.DataFrame, path: str) -> None:
        df.to_csv(path, index=False)
        logger.info("Saved %d rows to %s", len(df), path)
