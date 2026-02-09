import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TrendState(str, Enum):
    RANGING = "RANGING"
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    STRONG_BULLISH = "STRONG_BULLISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class TrendSignal:
    state: TrendState
    ma_fast: float
    ma_slow: float
    rsi: float
    adx: float
    should_pause: bool
    reason: str


class TrendDetector:
    def __init__(
        self,
        ma_fast_period: int = 20,
        ma_slow_period: int = 50,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        adx_period: int = 14,
        adx_strong_trend: float = 25.0,
        pause_on_strong_trend: bool = True,
    ) -> None:
        self._ma_fast_period = ma_fast_period
        self._ma_slow_period = ma_slow_period
        self._rsi_period = rsi_period
        self._rsi_overbought = rsi_overbought
        self._rsi_oversold = rsi_oversold
        self._adx_period = adx_period
        self._adx_strong_trend = adx_strong_trend
        self._pause_on_strong_trend = pause_on_strong_trend
        self._last_signal: Optional[TrendSignal] = None

    @property
    def last_signal(self) -> Optional[TrendSignal]:
        return self._last_signal

    def _compute_rsi(self, close: pd.Series) -> float:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.rolling(self._rsi_period).mean()
        avg_loss = loss.rolling(self._rsi_period).mean()

        last_avg_gain = avg_gain.iloc[-1]
        last_avg_loss = avg_loss.iloc[-1]

        if last_avg_loss == 0:
            return 100.0
        rs = last_avg_gain / last_avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _compute_adx(self, df: pd.DataFrame) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        period = self._adx_period

        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

        dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
        adx = dx.rolling(period).mean()

        last_val = adx.iloc[-1]
        return float(last_val) if not np.isnan(last_val) else 0.0

    def analyze(self, df: pd.DataFrame) -> TrendSignal:
        close = df["close"].astype(float)

        ma_fast = close.rolling(self._ma_fast_period).mean().iloc[-1]
        ma_slow = close.rolling(self._ma_slow_period).mean().iloc[-1]
        rsi = self._compute_rsi(close)
        adx = self._compute_adx(df)

        if ma_fast > ma_slow:
            base_trend = "BULLISH"
        elif ma_fast < ma_slow:
            base_trend = "BEARISH"
        else:
            base_trend = "RANGING"

        strong = adx >= self._adx_strong_trend
        should_pause = False
        reason = ""

        if base_trend == "BULLISH" and strong:
            state = TrendState.STRONG_BULLISH
            if self._pause_on_strong_trend:
                should_pause = True
                reason = f"Strong bullish trend (ADX={adx:.1f})"
        elif base_trend == "BEARISH" and strong:
            state = TrendState.STRONG_BEARISH
            if self._pause_on_strong_trend:
                should_pause = True
                reason = f"Strong bearish trend (ADX={adx:.1f})"
        elif base_trend == "BULLISH":
            state = TrendState.BULLISH
        elif base_trend == "BEARISH":
            state = TrendState.BEARISH
        else:
            state = TrendState.RANGING

        if self._pause_on_strong_trend and rsi >= self._rsi_overbought and strong:
            should_pause = True
            reason = f"Overbought + strong trend (RSI={rsi:.1f}, ADX={adx:.1f})"
        elif self._pause_on_strong_trend and rsi <= self._rsi_oversold and strong:
            should_pause = True
            reason = f"Oversold + strong trend (RSI={rsi:.1f}, ADX={adx:.1f})"

        signal = TrendSignal(
            state=state,
            ma_fast=round(ma_fast, 2),
            ma_slow=round(ma_slow, 2),
            rsi=round(rsi, 2),
            adx=round(adx, 2),
            should_pause=should_pause,
            reason=reason,
        )
        self._last_signal = signal

        logger.info(
            "Trend: %s | MA(fast=%.2f, slow=%.2f) RSI=%.2f ADX=%.2f pause=%s",
            state.value, ma_fast, ma_slow, rsi, adx, should_pause,
        )
        return signal

    def to_dict(self) -> Dict[str, Any]:
        if self._last_signal is None:
            return {"state": None, "should_pause": False}
        s = self._last_signal
        return {
            "state": s.state.value,
            "ma_fast": s.ma_fast,
            "ma_slow": s.ma_slow,
            "rsi": s.rsi,
            "adx": s.adx,
            "should_pause": s.should_pause,
            "reason": s.reason,
        }
