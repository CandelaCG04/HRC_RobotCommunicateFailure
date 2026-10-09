"""Per-face emotion state machine: turns smoothed predictions into stable state transitions."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from femotion.emotions import EMOTIONS


@dataclass(frozen=True)
class Transition:
    face_id: int
    t: float  # monotonic time at which the new state began (onset)
    previous: str | None
    emotion: str | None  # None = the face was lost / session ended
    confidence: float | None
    duration_ms: int | None  # how long ``previous`` lasted; None if there was no previous state


class EmotionStateMachine:
    """A new emotion becomes the stable state only after it has been the confident top
    class continuously for ``hold_s`` seconds. Any low-confidence or differing update
    restarts the candidate timer; the current stable state persists meanwhile.
    """

    def __init__(self, face_id: int, min_confidence: float = 0.5, hold_s: float = 0.5):
        self.face_id = face_id
        self.min_confidence = min_confidence
        self.hold_s = hold_s
        self.stable: str | None = None
        self.stable_confidence: float | None = None
        self._stable_since: float | None = None
        self._candidate: str | None = None
        self._candidate_since = 0.0

    def update(self, probs: np.ndarray, t: float) -> Transition | None:
        idx = int(np.argmax(probs))
        label, conf = EMOTIONS[idx], float(probs[idx])
        if self.stable is not None:
            self.stable_confidence = float(probs[EMOTIONS.index(self.stable)])

        if conf < self.min_confidence or label == self.stable:
            self._candidate = None
            return None
        if label != self._candidate:
            self._candidate, self._candidate_since = label, t
        if t - self._candidate_since < self.hold_s:
            return None

        onset = self._candidate_since
        transition = Transition(
            face_id=self.face_id,
            t=onset,
            previous=self.stable,
            emotion=label,
            confidence=conf,
            duration_ms=self._duration_ms(onset),
        )
        self.stable, self.stable_confidence, self._stable_since = label, conf, onset
        self._candidate = None
        return transition

    def close(self, t: float) -> Transition | None:
        """End the current stable state (face lost or session ended)."""
        if self.stable is None:
            return None
        transition = Transition(self.face_id, t, self.stable, None, None, self._duration_ms(t))
        self.stable = self.stable_confidence = self._stable_since = None
        self._candidate = None
        return transition

    def _duration_ms(self, until: float) -> int | None:
        if self._stable_since is None:
            return None
        return max(0, round((until - self._stable_since) * 1000))
