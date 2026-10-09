"""Frustration: an uncalibrated, configurable heuristic (no model outputs this class).

Fuses (a) negative valence / arousal from the emotion model, (b) the model's
angry+disgust+sad probability mass, and (c) facial-action proxies from MediaPipe
blendshapes linked to frustration in the literature (AU4 brow lowerer, AU7 lid
tightener, AU23/24 lip press, AU14 dimpler), measured relative to a per-face resting
baseline. A hysteresis state machine turns the score into logged transitions.
"""
from __future__ import annotations

import math

import numpy as np

from femotion.config import FrustrationConfig
from femotion.emotions import EMOTIONS
from femotion.smoothing import ProbabilityEMA
from femotion.state import Transition

BLENDSHAPE_FEATURES: dict[str, tuple[str, ...]] = {
    "brow_lower": ("browDownLeft", "browDownRight"),  # ~AU4
    "squint": ("eyeSquintLeft", "eyeSquintRight"),  # ~AU7
    "lip_press": ("mouthPressLeft", "mouthPressRight"),  # ~AU23/24
    "dimple": ("mouthDimpleLeft", "mouthDimpleRight"),  # ~AU14
}
MODEL_FEATURES = ("neg_valence", "arousal", "neg_emotions")
FEATURES = MODEL_FEATURES + tuple(BLENDSHAPE_FEATURES)
_NEG = [EMOTIONS.index(e) for e in ("angry", "disgust", "sad")]


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


class FrustrationEstimator:
    """Per-face frustration score in [0, 1]; None during the baseline warm-up."""

    def __init__(self, cfg: FrustrationConfig, t0: float):
        unknown = set(cfg.weights) - set(FEATURES)
        if unknown:
            raise ValueError(f"Unknown frustration weights {sorted(unknown)}; valid: {list(FEATURES)}")
        self.cfg = cfg
        self.t0 = t0
        self._baseline: dict[str, float] = {}
        self._baseline_t: float | None = None
        self._ema = ProbabilityEMA(cfg.score_tau_ms / 1000)
        self.score: float | None = None
        self.features: dict[str, float] = {}

    def update(
        self,
        t: float,
        probs: np.ndarray,
        valence: float,
        arousal: float,
        blendshapes: dict[str, float] | None,
        stable_emotion: str | None,
    ) -> float | None:
        groups = self._group(blendshapes) if blendshapes else None
        warming_up = t - self.t0 < self.cfg.warmup_s
        if groups is not None and (warming_up or stable_emotion == "neutral"):
            self._update_baseline(groups, t)
        if warming_up:
            return None

        feats = {
            "neg_emotions": _clip01(float(probs[_NEG].sum())),
            "neg_valence": _clip01(-valence),
            # arousal only counts when valence is negative (excited joy is not frustration)
            "arousal": _clip01(arousal) if valence < 0 else 0.0,
        }
        if groups is not None and self._baseline:
            scale = self.cfg.blendshape_scale
            for name, value in groups.items():
                feats[name] = _clip01((value - self._baseline[name]) / scale)

        # Weighted mean over the features available now (no mesh data -> renormalise).
        weights = {k: w for k, w in self.cfg.weights.items() if k in feats and w > 0}
        total = sum(weights.values())
        if total <= 0:
            return self.score
        raw = sum(w * feats[k] for k, w in weights.items()) / total
        self.features = feats
        self.score = float(self._ema.update(np.array([raw]), t)[0])
        return self.score

    @staticmethod
    def _group(blendshapes: dict[str, float]) -> dict[str, float]:
        return {
            name: float(np.mean([blendshapes.get(k, 0.0) for k in keys]))
            for name, keys in BLENDSHAPE_FEATURES.items()
        }

    def _update_baseline(self, groups: dict[str, float], t: float) -> None:
        if not self._baseline:
            self._baseline = dict(groups)
        else:
            dt = max(0.0, t - (self._baseline_t or t))
            alpha = 1 - math.exp(-dt / self.cfg.baseline_tau_s) if self.cfg.baseline_tau_s > 0 else 1.0
            # During warm-up converge quickly so the baseline reflects this person's resting face.
            if t - self.t0 < self.cfg.warmup_s:
                alpha = max(alpha, 0.2)
            for k, v in groups.items():
                self._baseline[k] += alpha * (v - self._baseline[k])
        self._baseline_t = t


class FrustrationStateMachine:
    """Hysteresis: enter after score >= on for hold_on; leave after score < off for hold_off."""

    LABEL = "frustrated"

    def __init__(self, face_id: int, on: float, off: float, hold_on_s: float, hold_off_s: float):
        self.face_id = face_id
        self.on, self.off, self.hold_on, self.hold_off = on, off, hold_on_s, hold_off_s
        self.active = False
        self._since: float | None = None  # onset of the active state
        self._pending: float | None = None  # start of a pending enter/exit

    def update(self, score: float | None, t: float) -> Transition | None:
        if score is None:
            return None
        if not self.active:
            if score < self.on:
                self._pending = None
                return None
            if self._pending is None:
                self._pending = t
            if t - self._pending < self.hold_on:
                return None
            self.active, self._since, self._pending = True, self._pending, None
            return Transition(self.face_id, self._since, None, self.LABEL, score, None)

        if score >= self.off:
            self._pending = None
            return None
        if self._pending is None:
            self._pending = t
        if t - self._pending < self.hold_off:
            return None
        end = self._pending
        return self._end(end, score)

    def close(self, t: float) -> Transition | None:
        return self._end(t, None) if self.active else None

    def _end(self, t: float, score: float | None) -> Transition:
        duration = max(0, round((t - self._since) * 1000))
        self.active, self._since, self._pending = False, None, None
        return Transition(self.face_id, t, self.LABEL, None, score, duration)
