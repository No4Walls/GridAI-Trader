import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.trend_detector import TrendDetector, TrendState


def _make_trending_data(direction: str = "up", n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    if direction == "up":
        close = 50000 + np.arange(n) * 50 + np.random.randn(n) * 10
    elif direction == "down":
        close = 60000 - np.arange(n) * 50 + np.random.randn(n) * 10
    else:
        close = 50000 + np.random.randn(n) * 100

    high = close + np.abs(np.random.randn(n) * 30)
    low = close - np.abs(np.random.randn(n) * 30)
    opn = close + np.random.randn(n) * 10
    volume = np.random.rand(n) * 1000

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_detect_bullish_trend():
    df = _make_trending_data("up", 200)
    detector = TrendDetector(adx_strong_trend=15)
    signal = detector.analyze(df)
    assert signal.state in (TrendState.BULLISH, TrendState.STRONG_BULLISH)
    assert signal.ma_fast > 0
    assert signal.ma_slow > 0


def test_detect_bearish_trend():
    df = _make_trending_data("down", 200)
    detector = TrendDetector(adx_strong_trend=15)
    signal = detector.analyze(df)
    assert signal.state in (TrendState.BEARISH, TrendState.STRONG_BEARISH)


def test_ranging_market():
    df = _make_trending_data("range", 200)
    detector = TrendDetector(adx_strong_trend=50)
    signal = detector.analyze(df)
    assert signal.adx >= 0


def test_pause_on_strong_trend():
    df = _make_trending_data("up", 200)
    detector = TrendDetector(adx_strong_trend=10, pause_on_strong_trend=True)
    signal = detector.analyze(df)
    if signal.adx >= 10:
        assert signal.should_pause


def test_no_pause_when_disabled():
    df = _make_trending_data("up", 200)
    detector = TrendDetector(pause_on_strong_trend=False)
    signal = detector.analyze(df)
    assert not signal.should_pause


def test_rsi_in_range():
    df = _make_trending_data("range", 200)
    detector = TrendDetector()
    signal = detector.analyze(df)
    assert 0 <= signal.rsi <= 100


def test_to_dict():
    df = _make_trending_data("up", 200)
    detector = TrendDetector()
    detector.analyze(df)
    d = detector.to_dict()
    assert "state" in d
    assert "rsi" in d
    assert "adx" in d
    assert "should_pause" in d


def test_last_signal_stored():
    df = _make_trending_data("up", 200)
    detector = TrendDetector()
    assert detector.last_signal is None
    detector.analyze(df)
    assert detector.last_signal is not None
