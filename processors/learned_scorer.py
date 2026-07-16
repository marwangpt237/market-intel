"""
Learned Scorer — linear model with learned weights, updated via online SGD.

Model:
    score = Σ(feature_value × weight) + bias

Prediction:
    predict(features) → float (clamped 0-100)

Update (online gradient descent):
    For each (features, actual_outcome) pair:
      prediction = predict(features)
      error = prediction - actual_outcome
      for each feature (name, value):
        gradient_w = error * value + lambda * current_weight
        new_weight = current_weight - learning_rate * gradient_w
        samples += 1
      bias -= learning_rate * error

Cold-start handling:
    If a feature has < COLD_START_SAMPLES observations, use its baseline
    weight (from BASELINE_WEIGHTS) instead of the learned weight. This
    prevents wild swings early when sample size is small.

Regularization:
    L2 penalty (lambda) prevents any single weight from growing unbounded.
    Default lambda = 0.001 (gentle).

Learning rate:
    Default 0.01. With ~25 features and outcomes 0-100, this gives
    stable convergence after ~50-100 samples per feature.

Outcome normalization:
    Outcomes from the actions table are:
      outcome = clicks * 1 + signups * 5 + conversions * 25 + revenue * 0.1
    These can range 0 to ~1000+. We normalize to 0-100 by clamping
    at 100 (anything above 100 is treated as 100).
"""
from __future__ import annotations

import math
from core.logger import get_logger
from processors.feature_extractor import (
    FeatureVector,
    BASELINE_WEIGHTS,
    BASELINE_BIAS,
    COLD_START_SAMPLES,
)
from storage.feature_weights_store import FeatureWeightsStore


# Default hyperparameters
DEFAULT_LEARNING_RATE = 0.01
DEFAULT_REGULARIZATION = 0.001  # L2 penalty
OUTCOME_CLAMP_MAX = 100.0  # outcomes above this are clamped
SCORE_MIN = 0.0
SCORE_MAX = 100.0


class LearnedScorer:
    """Linear model with online-SGD-learned weights.

    Usage:
        scorer = LearnedScorer(db_path)
        scorer.load()  # load weights from SQLite

        # Predict
        features = extractor.extract(decision, items)
        score = scorer.predict(features)

        # Update from observed outcome
        scorer.update(features, actual_outcome=42.5)
        scorer.save()  # persist to SQLite
    """

    def __init__(
        self,
        db_path: str,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        regularization: float = DEFAULT_REGULARIZATION,
    ):
        self._db_path = db_path
        self._learning_rate = learning_rate
        self._regularization = regularization
        self._logger = get_logger("learned_scorer")
        self._store = FeatureWeightsStore(db_path)

        # In-memory weight cache: {feature_name: {weight, baseline, samples, total_gradient}}
        self._weights: dict[str, dict] = {}
        self._bias: float = BASELINE_BIAS
        self._bias_samples: int = 0

    # ─── Loading / saving ────────────────────────────────────────────────

    def load(self) -> None:
        """Load all weights from SQLite into memory."""
        all_weights = self._store.load_all()
        self._weights = {}

        for name, record in all_weights.items():
            if name == "__bias__":
                self._bias = record["weight"]
                self._bias_samples = record["samples"]
            else:
                self._weights[name] = {
                    "weight": record["weight"],
                    "baseline": record["baseline_weight"],
                    "samples": record["samples"],
                    "total_gradient": record["total_gradient"],
                }

        self._logger.info(
            f"Loaded {len(self._weights)} feature weights (bias={self._bias:.2f}, bias_samples={self._bias_samples})"
        )

    def save(self) -> None:
        """Persist all in-memory weights to SQLite."""
        for name, record in self._weights.items():
            self._store.upsert(
                feature_name=name,
                weight=record["weight"],
                baseline_weight=record["baseline"],
                samples=record["samples"],
                total_gradient=record["total_gradient"],
            )
        # Save bias
        self._store.upsert(
            feature_name="__bias__",
            weight=self._bias,
            baseline_weight=BASELINE_BIAS,
            samples=self._bias_samples,
            total_gradient=0.0,
        )

    # ─── Prediction ─────────────────────────────────────────────────────

    def predict(self, features: FeatureVector) -> float:
        """Predict the score for a feature vector.

        For features with insufficient samples (< COLD_START_SAMPLES),
        use the baseline weight instead of the learned weight.
        """
        score = self._bias

        for name, value in features.features.items():
            weight = self._get_effective_weight(name)
            score += value * weight

        return max(SCORE_MIN, min(SCORE_MAX, score))

    def _get_effective_weight(self, feature_name: str) -> float:
        """Get the weight to use for a feature.

        Uses learned weight if samples >= COLD_START_SAMPLES, else baseline.
        """
        record = self._weights.get(feature_name)
        if record and record["samples"] >= COLD_START_SAMPLES:
            return record["weight"]
        # Fallback to baseline
        if record:
            return record["baseline"]
        return BASELINE_WEIGHTS.get(feature_name, 0.0)

    # ─── Update ─────────────────────────────────────────────────────────

    def update(self, features: FeatureVector, actual_outcome: float) -> float:
        """Update weights from an observed outcome.

        Args:
            features: feature vector for the action
            actual_outcome: observed outcome (e.g. 42.5)

        Returns:
            The prediction error (prediction - actual). Negative means
            we under-predicted; positive means we over-predicted.
        """
        # Clamp outcome
        actual = max(0.0, min(OUTCOME_CLAMP_MAX, float(actual_outcome)))

        # Make prediction
        prediction = self.predict(features)
        error = prediction - actual

        # Update each feature weight via SGD
        for name, value in features.features.items():
            self._update_single_weight(name, value, error)

        # Update bias
        bias_gradient = error  # gradient of bias = error (since bias has no input)
        self._bias -= self._learning_rate * bias_gradient
        self._bias = max(-50.0, min(50.0, self._bias))  # clamp bias to reasonable range
        self._bias_samples += 1

        return error

    def _update_single_weight(self, feature_name: str, value: float, error: float) -> None:
        """Update a single feature's weight via gradient descent.

        gradient = error * value + lambda * current_weight
        new_weight = current_weight - learning_rate * gradient
        """
        # Initialize record if not present
        if feature_name not in self._weights:
            self._weights[feature_name] = {
                "weight": BASELINE_WEIGHTS.get(feature_name, 0.0),
                "baseline": BASELINE_WEIGHTS.get(feature_name, 0.0),
                "samples": 0,
                "total_gradient": 0.0,
            }

        record = self._weights[feature_name]
        current_weight = record["weight"]

        # Compute gradient (with L2 regularization)
        gradient = error * value + self._regularization * current_weight

        # Update weight
        new_weight = current_weight - self._learning_rate * gradient

        # Clamp weight to reasonable range (prevent runaway)
        new_weight = max(-100.0, min(100.0, new_weight))

        record["weight"] = new_weight
        record["samples"] += 1
        record["total_gradient"] += abs(gradient)

    # ─── Diagnostics ────────────────────────────────────────────────────

    def get_feature_importance(self) -> list[dict]:
        """Get features sorted by absolute weight (most influential first)."""
        records = []
        for name, record in self._weights.items():
            records.append({
                "feature": name,
                "weight": record["weight"],
                "baseline": record["baseline"],
                "samples": record["samples"],
                "delta_from_baseline": record["weight"] - record["baseline"],
                "total_gradient": record["total_gradient"],
                "avg_gradient": record["total_gradient"] / max(1, record["samples"]),
            })

        # Sort by absolute weight (descending)
        records.sort(key=lambda r: abs(r["weight"]), reverse=True)
        return records

    def get_stats(self) -> dict:
        """Get aggregate stats about the learned model."""
        total_features = len(self._weights)
        features_with_samples = sum(1 for r in self._weights.values() if r["samples"] > 0)
        features_with_enough = sum(1 for r in self._weights.values() if r["samples"] >= COLD_START_SAMPLES)
        total_samples = sum(r["samples"] for r in self._weights.values())

        # Find biggest positive and negative shifts from baseline
        biggest_positive_shift = None
        biggest_negative_shift = None
        for name, record in self._weights.items():
            if record["samples"] < COLD_START_SAMPLES:
                continue
            delta = record["weight"] - record["baseline"]
            if biggest_positive_shift is None or delta > biggest_positive_shift["delta"]:
                biggest_positive_shift = {"feature": name, "delta": delta, "weight": record["weight"], "baseline": record["baseline"]}
            if biggest_negative_shift is None or delta < biggest_negative_shift["delta"]:
                biggest_negative_shift = {"feature": name, "delta": delta, "weight": record["weight"], "baseline": record["baseline"]}

        return {
            "total_features": total_features,
            "features_with_samples": features_with_samples,
            "features_with_enough_samples": features_with_enough,
            "total_samples": total_samples,
            "bias": self._bias,
            "bias_samples": self._bias_samples,
            "biggest_positive_shift": biggest_positive_shift,
            "biggest_negative_shift": biggest_negative_shift,
            "cold_start_threshold": COLD_START_SAMPLES,
            "learning_rate": self._learning_rate,
            "regularization": self._regularization,
        }

    def get_store_stats(self) -> dict:
        """Delegate to the underlying store for on-disk stats."""
        return self._store.get_stats()
