"""The predictive BTC direction model -- THE source of direction as of
this round (see engine.py's module docstring). Estimates a real,
calibrated P(UP)/P(DOWN) for the CURRENT 15-minute contract from
btc_features.BtcFeatureVector, to be compared against Polymarket's own
implied probability (see btc_model_entry_signal.py) rather than ever
treating Polymarket's own price as the prediction itself.

NOT HAND-WRITTEN WEIGHTS: per explicit instruction, this module never
ships a hardcoded coefficient vector dressed up as a "trained" model.
BtcDirectionModel.fit() is a real logistic regression fit by gradient
descent on labeled historical examples (see btc_training_data.py for
how those are built, and scripts/backtest_btc_direction_model.py for
the walk-forward evaluation that produces and validates one). A model
file this module loads is JSON: feature order, per-feature
mean/stdev (for standardization, fit on the SAME training data the
weights came from), weights, intercept, and metadata (trained_at,
training_example_count, data_source -- "synthetic" vs real, so a demo
weights file produced against synthetic data can never be silently
mistaken for one proven against real BTC history). If no weights file
is configured/loadable, BtcDirectionModel.untrained() stands in: it
always returns a 50/50 prediction with is_trained=False, so a caller
that forgets to check is_trained gets a probability with ZERO edge
over a fair coin, never a confident-looking fabrication -- see
btc_model_entry_signal.py, which treats is_trained=False as a hard
NO_TRADE condition regardless of any configured minimum edge.

Standardization (zero mean, unit variance per feature, using the
TRAINING set's own mean/stdev, never a separately-reasoned-about
"typical" range) is the only preprocessing -- plain logistic
regression on top, no hidden second model. This keeps the model fully
inspectable: `coefficients` is a real dict of feature_name -> weight a
human can read directly off the saved JSON file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polymarket.btc_features import FEATURE_NAMES, BtcFeatureVector

DATA_SOURCE_SYNTHETIC = "synthetic"
DATA_SOURCE_REAL = "real"


class BtcDirectionModelError(RuntimeError):
    """Raised when a model file is missing, corrupted, or shaped wrong."""


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass(frozen=True)
class BtcDirectionPrediction:
    """The full, inspectable model output -- this round's required
    structured result. `predicted_up_probability` is the model's own
    calibrated estimate of P(UP) for the CURRENT 15-minute contract;
    `favored_outcome` is simply whichever of UP/DOWN that implies
    (>0.5), carried separately so a caller never has to re-derive it
    (and so an exact 0.5 -- genuinely undecided -- reads as
    favored_outcome=None, never an arbitrary tie-break)."""

    predicted_up_probability: float
    predicted_down_probability: float
    favored_outcome: str | None  # "UP" | "DOWN" | None (exactly 0.5)
    is_trained: bool
    feature_timestamp: datetime
    time_remaining: float | None
    price_to_beat: float | None
    current_btc_price: float | None
    model_version: str | None  # trained_at timestamp string from the loaded model file, or None (untrained)
    data_source: str | None  # DATA_SOURCE_REAL | DATA_SOURCE_SYNTHETIC | None (untrained)

    def to_log_fields(self) -> dict[str, float | str | None]:
        return {
            "MODEL_UP_PROBABILITY": self.predicted_up_probability,
            "MODEL_DOWN_PROBABILITY": self.predicted_down_probability,
            "MODEL_IS_TRAINED": self.is_trained,
            "MODEL_VERSION": self.model_version,
            "MODEL_DATA_SOURCE": self.data_source,
        }


@dataclass(frozen=True)
class BtcDirectionModel:
    """Immutable. `coefficients`/`feature_means`/`feature_stdevs` are
    keyed by the SAME FEATURE_NAMES btc_features.py defines -- never a
    second, independently-ordered feature list. An untrained instance
    (see untrained()) has empty coefficients and is_trained=False;
    predict() on it always returns a flat 50/50 regardless of
    features, by construction (sigmoid(0) == 0.5)."""

    coefficients: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    feature_means: dict[str, float] = field(default_factory=dict)
    feature_stdevs: dict[str, float] = field(default_factory=dict)
    is_trained: bool = False
    trained_at: str | None = None
    training_example_count: int = 0
    data_source: str | None = None

    @classmethod
    def untrained(cls) -> "BtcDirectionModel":
        return cls()

    def _standardize(self, features: dict[str, float]) -> dict[str, float]:
        out = {}
        for name in FEATURE_NAMES:
            value = features.get(name, 0.0)
            mean = self.feature_means.get(name, 0.0)
            stdev = self.feature_stdevs.get(name, 1.0) or 1.0
            out[name] = (value - mean) / stdev
        return out

    def predict_proba(self, features: dict[str, float]) -> float:
        """Raw P(UP) in [0, 1] from a feature dict (see
        BtcFeatureVector.as_feature_dict()) -- 0.5 for an untrained
        model by construction, never a guess dressed up as a number."""
        if not self.is_trained:
            return 0.5
        standardized = self._standardize(features)
        z = self.intercept + sum(self.coefficients.get(name, 0.0) * standardized[name] for name in FEATURE_NAMES)
        return _sigmoid(z)

    def predict(self, vector: BtcFeatureVector) -> BtcDirectionPrediction:
        """The structured, loggable prediction for one feature
        vector. Deliberately does NOT gate on vector.has_minimum_data
        itself -- btc_model_entry_signal.py is the one place that
        decides what "not enough data" means for the trade decision;
        this always returns a real, honestly-computed number (0.5 for
        missing-data-imputed-to-0 features, same as any other
        untrained-adjacent degenerate input)."""
        up = self.predict_proba(vector.as_feature_dict())
        down = 1.0 - up
        if up > 0.5:
            favored = "UP"
        elif down > 0.5:
            favored = "DOWN"
        else:
            favored = None
        return BtcDirectionPrediction(
            predicted_up_probability=up, predicted_down_probability=down, favored_outcome=favored,
            is_trained=self.is_trained, feature_timestamp=vector.at, time_remaining=vector.time_remaining_seconds,
            price_to_beat=vector.price_to_beat, current_btc_price=vector.current_price,
            model_version=self.trained_at, data_source=self.data_source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "coefficients": self.coefficients, "intercept": self.intercept,
            "feature_means": self.feature_means, "feature_stdevs": self.feature_stdevs,
            "is_trained": self.is_trained, "trained_at": self.trained_at,
            "training_example_count": self.training_example_count, "data_source": self.data_source,
            "feature_names": list(FEATURE_NAMES),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BtcDirectionModel":
        saved_names = data.get("feature_names")
        if saved_names is not None and list(saved_names) != list(FEATURE_NAMES):
            raise BtcDirectionModelError(
                f"Model file's feature_names {saved_names!r} do not match the current "
                f"btc_features.FEATURE_NAMES {list(FEATURE_NAMES)!r} -- refusing to load a model trained "
                "against a different feature set; retrain it."
            )
        return cls(
            coefficients=dict(data.get("coefficients", {})), intercept=float(data.get("intercept", 0.0)),
            feature_means=dict(data.get("feature_means", {})), feature_stdevs=dict(data.get("feature_stdevs", {})),
            is_trained=bool(data.get("is_trained", False)), trained_at=data.get("trained_at"),
            training_example_count=int(data.get("training_example_count", 0)), data_source=data.get("data_source"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "BtcDirectionModel":
        if not path.is_file():
            raise BtcDirectionModelError(f"Model file {path} does not exist")
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BtcDirectionModelError(f"Model file {path} is corrupted or unreadable: {exc}") from exc

    @classmethod
    def load_or_untrained(cls, path: Path | None) -> "BtcDirectionModel":
        """Never raises -- a missing/unconfigured model file degrades
        to untrained() (always 50/50, is_trained=False), which
        btc_model_entry_signal.py's hard gate then turns into NO_TRADE.
        A CORRUPTED file (exists but unreadable) still raises via
        load() -- that is a real configuration problem, never silently
        papered over the same way "not configured yet" is."""
        if path is None or not path.is_file():
            return cls.untrained()
        return cls.load(path)

    @classmethod
    def fit(
        cls, examples: list[tuple[dict[str, float], int]], *, learning_rate: float = 0.1, epochs: int = 500,
        l2: float = 0.01, data_source: str = DATA_SOURCE_REAL, now: datetime | None = None,
    ) -> "BtcDirectionModel":
        """Real logistic regression, fit by batch gradient descent on
        standardized features, minimizing L2-regularized log-loss.
        `examples` is (feature_dict, label) pairs, label 1 == UP, 0 ==
        DOWN. Pure Python (no numpy dependency) -- these datasets are
        a few thousand rows over ~10 features at most, well within
        what a plain Python loop handles in well under a second."""
        if not examples:
            raise BtcDirectionModelError("Cannot fit a model on zero examples")
        now = now or datetime.now(timezone.utc)
        n = len(examples)

        means = {name: sum(f.get(name, 0.0) for f, _ in examples) / n for name in FEATURE_NAMES}
        stdevs = {}
        for name in FEATURE_NAMES:
            variance = sum((f.get(name, 0.0) - means[name]) ** 2 for f, _ in examples) / n
            stdevs[name] = math.sqrt(variance) or 1.0  # a constant feature gets stdev 1 (never divide by 0)

        standardized_rows = []
        labels = []
        for features, label in examples:
            standardized_rows.append({name: (features.get(name, 0.0) - means[name]) / stdevs[name] for name in FEATURE_NAMES})
            labels.append(float(label))

        weights = {name: 0.0 for name in FEATURE_NAMES}
        intercept = 0.0

        for _ in range(epochs):
            grad_w = {name: 0.0 for name in FEATURE_NAMES}
            grad_b = 0.0
            for row, label in zip(standardized_rows, labels):
                z = intercept + sum(weights[name] * row[name] for name in FEATURE_NAMES)
                pred = _sigmoid(z)
                error = pred - label
                for name in FEATURE_NAMES:
                    grad_w[name] += error * row[name]
                grad_b += error
            for name in FEATURE_NAMES:
                weights[name] -= learning_rate * (grad_w[name] / n + l2 * weights[name])
            intercept -= learning_rate * (grad_b / n)

        return cls(
            coefficients=weights, intercept=intercept, feature_means=means, feature_stdevs=stdevs,
            is_trained=True, trained_at=now.isoformat(), training_example_count=n, data_source=data_source,
        )
