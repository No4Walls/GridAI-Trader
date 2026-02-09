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
        max_retries: int = 5,
        resume_path: Optional[str] = None,
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

        all_candles: list = []
        current_since = since

        if resume_path:
            from pathlib import Path
            rp = Path(resume_path)
            if rp.exists():
                partial = pd.read_csv(rp)
                if len(partial) > 0 and "timestamp" in partial.columns:
                    all_candles = partial.values.tolist()
                    last_ms = int(pd.to_datetime(partial["timestamp"].iloc[-1]).timestamp() * 1000)
                    current_since = last_ms + 1
                    logger.info("Resumed from %s (%d rows, continuing from %s)", resume_path, len(partial), partial["timestamp"].iloc[-1])

        total_ms = end_ts - since
        chunk_count = 0

        while current_since < end_ts:
            retries = 0
            candles = None
            while retries < max_retries:
                try:
                    candles = self._exchange.fetch_ohlcv(
                        self._trading_pair,
                        timeframe=timeframe,
                        since=current_since,
                        limit=limit_per_request,
                    )
                    break
                except ccxt.RateLimitExceeded:
                    retries += 1
                    wait = 10 * retries
                    logger.warning("Rate limit hit, retry %d/%d (waiting %ds)", retries, max_retries, wait)
                    time.sleep(wait)
                except ccxt.NetworkError as e:
                    retries += 1
                    wait = 5 * retries
                    logger.warning("Network error: %s, retry %d/%d (waiting %ds)", e, retries, max_retries, wait)
                    time.sleep(wait)
                except ccxt.BaseError as e:
                    logger.error("Exchange error fetching OHLCV: %s", e)
                    raise

            if candles is None:
                logger.error("Failed to fetch chunk after %d retries, saving partial progress", max_retries)
                break

            if not candles:
                break

            all_candles.extend(candles)
            last_ts = candles[-1][0]
            if last_ts <= current_since:
                break
            current_since = last_ts + 1
            chunk_count += 1

            elapsed_ms = current_since - since
            pct = min(100.0, elapsed_ms / total_ms * 100) if total_ms > 0 else 100.0
            if chunk_count % 10 == 0:
                logger.info("Fetch progress: %.1f%% (%d candles)", pct, len(all_candles))
                if resume_path:
                    self._save_partial(all_candles, resume_path)

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

    def _save_partial(self, candles: list, path: str) -> None:
        try:
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.to_csv(path, index=False)
        except Exception:
            logger.warning("Failed to save partial progress to %s", path)

    def load_from_csv(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def save_to_csv(self, df: pd.DataFrame, path: str) -> None:
        df.to_csv(path, index=False)
        logger.info("Saved %d rows to %s", len(df), path)
