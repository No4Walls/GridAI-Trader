import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.volatility_classifier import (
    VolatilityClassifier,
    VolatilityRegime,
    compute_features,
    label_regimes,
)


def _make_ohlcv(n: int = 500) -> pd.DataFrame:
    np.random.seed(42)
    close = 50000 + np.cumsum(np.random.randn(n) * 100)
    high = close + np.abs(np.random.randn(n) * 50)
    low = close - np.abs(np.random.randn(n) * 50)
    opn = close + np.random.randn(n) * 20
    volume = np.random.rand(n) * 1000
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_compute_features():
    df = _make_ohlcv(500)
    features = compute_features(df)
    assert len(features) > 0
    assert "atr_14" in features.columns
    assert "bb_width" in features.columns
    assert "variance_5m" in features.columns
    assert "variance_1h" in features.columns


def test_label_regimes():
    df = _make_ohlcv(500)
    features = compute_features(df)
    labels = label_regimes(features)
    assert len(labels) == len(features)
    assert set(labels.unique()).issubset({0, 1, 2})


def test_train_and_predict():
    df = _make_ohlcv(1000)
    classifier = VolatilityClassifier(model_path="/tmp/test_vol_model.joblib")
    results = classifier.train(df, n_estimators=10)
    assert "accuracy" in results
    assert results["accuracy"] > 0

    regime, confidence = classifier.predict(df.tail(200))
    assert isinstance(regime, VolatilityRegime)
    assert 0 <= confidence <= 1


def test_predict_without_model():
    classifier = VolatilityClassifier(model_path="/tmp/nonexistent_model.joblib")
    df = _make_ohlcv(200)
    regime, confidence = classifier.predict(df)
    assert regime == VolatilityRegime.MEDIUM
    assert confidence == 0.0


def test_to_dict():
    classifier = VolatilityClassifier()
    d = classifier.to_dict()
    assert "regime" in d
    assert "confidence" in d
    assert "model_loaded" in d


def test_load_nonexistent_model():
    classifier = VolatilityClassifier(model_path="/tmp/does_not_exist.joblib")
    assert not classifier.load_model()
