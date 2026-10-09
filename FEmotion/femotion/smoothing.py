"""Temporal smoothing of class-probability vectors."""
from __future__ import annotations

import math

import numpy as np


class ProbabilityEMA:
    """Exponential moving average with a time constant, so it is independent of the update rate."""

    def __init__(self, tau_s: float):
        self.tau_s = tau_s
        self.value: np.ndarray | None = None
        self._last_t: float | None = None

    def update(self, probs: np.ndarray, t: float) -> np.ndarray:
        probs = np.asarray(probs, dtype=np.float64)
        if self.value is None or self._last_t is None:
            self.value = probs.copy()
        else:
            dt = max(0.0, t - self._last_t)
            alpha = 1.0 if self.tau_s <= 0 else 1.0 - math.exp(-dt / self.tau_s)
            self.value += alpha * (probs - self.value)
        self._last_t = t
        return self.value
