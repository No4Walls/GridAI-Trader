import logging
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

logger = logging.getLogger(__name__)


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


REGIME_LABELS = {0: VolatilityRegime.LOW, 1: VolatilityRegime.MEDIUM, 2: VolatilityRegime.HIGH}
REGIME_TO_INT = {v: k for k, v in REGIME_LABELS.items()}


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    features = pd.DataFrame(index=df.index)

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    features["atr_14"] = tr.rolling(14).mean()

    sma_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    features["bb_width"] = (2 * std_20) / sma_20

    features["variance_5m"] = close.rolling(12).var()

    features["variance_1h"] = close.rolling(12 * 12).var()

    features["returns_std"] = close.pct_change().rolling(24).std()

    features["range_pct"] = (high - low) / close * 100

    features = features.dropna()
    return features


def label_regimes(features: pd.DataFrame) -> pd.Series:
    atr = features["atr_14"]
    q33 = atr.quantile(0.33)
    q66 = atr.quantile(0.66)

    labels = pd.Series(1, index=features.index, dtype=int)
    labels[atr <= q33] = 0
    labels[atr >= q66] = 2
    return labels


class VolatilityClassifier:
    def __init__(self, model_path: str = "models/volatility_model.joblib") -> None:
        self._model_path = model_path
        self._model: Optional[RandomForestClassifier] = None
        self._feature_cols = [
            "atr_14", "bb_width", "variance_5m", "variance_1h",
            "returns_std", "range_pct",
        ]
        self._last_prediction: Optional[VolatilityRegime] = None
        self._last_confidence: float = 0.0

    @property
    def last_prediction(self) -> Optional[VolatilityRegime]:
        return self._last_prediction

    @property
    def last_confidence(self) -> float:
        return self._last_confidence

    def load_model(self) -> bool:
        path = Path(self._model_path)
        if not path.exists():
            logger.warning("Model file not found: %s", self._model_path)
            return False
        try:
            self._model = joblib.load(path)
            logger.info("Volatility model loaded from %s", self._model_path)
            return True
        except Exception:
            logger.exception("Failed to load model")
            return False

    def train(
        self,
        df: pd.DataFrame,
        test_size: float = 0.2,
        n_estimators: int = 100,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        features = compute_features(df)
        labels = label_regimes(features)

        X = features[self._feature_cols].values
        y = labels.values

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, shuffle=False
        )

        self._model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=10,
            min_samples_split=20,
            min_samples_leaf=10,
            random_state=random_state,
            n_jobs=-1,
        )
        self._model.fit(X_train, y_train)

        y_pred = self._model.predict(X_test)
        report = classification_report(y_test, y_pred, output_dict=True)

        Path(self._model_path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, self._model_path)
        logger.info("Model trained and saved to %s", self._model_path)

        accuracy = report.get("accuracy", 0.0)
        logger.info("Training accuracy: %.4f", accuracy)
        return {"accuracy": accuracy, "report": report}

    def predict(self, df: pd.DataFrame) -> Tuple[VolatilityRegime, float]:
        if self._model is None:
            logger.warning("Model not loaded, defaulting to MEDIUM")
            self._last_prediction = VolatilityRegime.MEDIUM
            self._last_confidence = 0.0
            return VolatilityRegime.MEDIUM, 0.0

        features = compute_features(df)
        if features.empty:
            self._last_prediction = VolatilityRegime.MEDIUM
            self._last_confidence = 0.0
            return VolatilityRegime.MEDIUM, 0.0

        last_row = features[self._feature_cols].iloc[[-1]].values
        pred = self._model.predict(last_row)[0]
        proba = self._model.predict_proba(last_row)[0]
        confidence = float(proba[pred])

        regime = REGIME_LABELS.get(pred, VolatilityRegime.MEDIUM)
        self._last_prediction = regime
        self._last_confidence = confidence

        logger.info("Volatility prediction: %s (confidence=%.3f)", regime.value, confidence)
        return regime, confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self._last_prediction.value if self._last_prediction else None,
            "confidence": self._last_confidence,
            "model_loaded": self._model is not None,
        }
