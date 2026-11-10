"""Component reconstruction for AA Intelligence Index v5 configurations AA has not scored.

WHY THIS FILE EXISTS
--------------------
Intelligence Index v5 combines nine evaluations. AA publishes a v5 score only when a
configuration has all nine, but it publishes the individual evaluations it has run. Many
configurations the plans serve have some of the nine plus AA's older benchmarks, and no
v5 score.

On the configurations AA did score, v5 is almost exactly a fixed linear combination of the
nine evaluations (R2 0.999, worst error 2.0 points on 109 configurations, 2026-11-09). So a
missing configuration can be rebuilt from AA's own numbers:

  1. Each missing evaluation is imputed by a ridge least-squares fit on the configuration's
     measured AA benchmarks, trained on the configurations AA scored.
  2. The fitted v5 combination is applied to the measured plus imputed evaluations.

The error band is measured, not assumed: every scored configuration is re-estimated with
the same evaluations hidden that the target is missing and with both fits redone without
it (leave-one-out), and the band is
the 90th percentile of the absolute error. A reconstruction needs at least MIN_PRESENT
measured v5 evaluations; with fewer the band exceeds 7 points, close to the single-benchmark
bridge proxy_estimates.py rejects, so those configurations stay unscored.

Inputs are compact records as stored in the snapshot's rawRecords: a "benchmarks" map keyed
by AA evaluation slug. Everything needed to repeat an estimate is in the snapshot itself.
"""
from __future__ import annotations

import numpy as np

COMPONENTS = ("aa-briefcase", "automationbench-aa", "terminalbench-4-0", "frontiercode-2-0", "omniscience",
              "gdp-pdf", "hle-diamond", "critpt-v2-hard", "terminal-bench-science")
MIN_PRESENT = 4   # measured v5 evaluations required; 3 or fewer give a p90 band above 7 points
MIN_TRAIN = 25    # scored configurations needed to fit one imputation
RIDGE = 1e-3      # per-row ridge strength; keeps collinear benchmark fits stable


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class Reconstructor:
    def __init__(self, records: list[dict]):
        """records: compact AA records; those with a measured v5 score and all nine evaluations train the fit."""
        self.train = [(r["benchmarks"], r["intelligenceIndex"]) for r in records
                      if number(r.get("intelligenceIndex")) is not None and not r.get("intelligenceIndexIsEstimated")
                      and all(c in r.get("benchmarks", {}) for c in COMPONENTS)]
        if len(self.train) < MIN_TRAIN:
            raise ValueError(f"only {len(self.train)} fully scored configurations; need {MIN_TRAIN}")
        self._X = np.array([[v[c] for c in COMPONENTS] + [1.0] for v, _ in self.train])
        self._y = np.array([s for _, s in self.train])
        self.weights, *_ = np.linalg.lstsq(self._X, self._y, rcond=None)
        resid = self._y - self._X @ self.weights
        self.r2 = float(1 - resid.var() / self._y.var())
        self.max_error = float(abs(resid).max())
        self._fold_weights = None

    def _fold(self, i: int):
        """Combination weights fitted without scored configuration i, for honest leave-one-out."""
        if self._fold_weights is None:
            keep = np.ones(len(self.train), dtype=bool)
            self._fold_weights = []
            for j in range(len(self.train)):
                keep[j] = False
                self._fold_weights.append(np.linalg.lstsq(self._X[keep], self._y[keep], rcond=None)[0])
                keep[j] = True
        return self._fold_weights[i]

    def _impute(self, target: str, vec: dict, train: list) -> float | None:
        preds = sorted(k for k in vec if k != target
                       and sum(1 for v, _ in train if k in v and target in v) >= MIN_TRAIN)
        rows = [v for v, _ in train if target in v and all(p in v for p in preds)]
        while preds and len(rows) < MIN_TRAIN:
            preds.remove(min(preds, key=lambda p: (sum(1 for v, _ in train if p in v), p)))
            rows = [v for v, _ in train if target in v and all(p in v for p in preds)]
        if len(rows) < MIN_TRAIN:
            return None
        X = np.array([[v[p] for p in preds] + [1.0] for v in rows])
        y = np.array([v[target] for v in rows])
        w = np.linalg.solve(X.T @ X + RIDGE * len(rows) * np.eye(X.shape[1]), X.T @ y)
        return float(np.array([vec[p] for p in preds] + [1.0]) @ w)

    def estimate(self, vec: dict, train: list | None = None, weights=None) -> float | None:
        train = self.train if train is None else train
        weights = self.weights if weights is None else weights
        if sum(1 for c in COMPONENTS if c in vec) < MIN_PRESENT:
            return None
        full = dict(vec)
        for c in COMPONENTS:
            if c not in full:
                value = self._impute(c, vec, train)
                if value is None:
                    return None
                full[c] = value
        return float(np.array([full[c] for c in COMPONENTS] + [1.0]) @ weights)

    def band(self, vec: dict) -> dict | None:
        """Leave-one-out error with the target's missing evaluations hidden on every scored configuration.

        Both stages (imputation and combination) are refitted without the held-out configuration."""
        missing = [c for c in COMPONENTS if c not in vec]
        errors = []
        for i, (v, y) in enumerate(self.train):
            masked = {k: x for k, x in v.items() if k not in missing and (k in vec or k in COMPONENTS)}
            est = self.estimate(masked, self.train[:i] + self.train[i + 1:], self._fold(i))
            if est is not None:
                errors.append(abs(est - y))
        if len(errors) < MIN_TRAIN:
            return None
        return {"p90": float(np.percentile(errors, 90)), "median": float(np.median(errors)), "n": len(errors)}

    def reconstruct(self, record: dict) -> dict | None:
        """Return the estimate and its provenance for one compact record, or None."""
        vec = record.get("benchmarks", {})
        value = self.estimate(vec)
        if value is None:
            return None
        band = self.band(vec)
        if band is None:
            return None
        return {
            "value": value,
            "band": band["p90"],
            "median_error": band["median"],
            "validated_on": band["n"],
            "measured_components": [c for c in COMPONENTS if c in vec],
            "imputed_components": [c for c in COMPONENTS if c not in vec],
        }
