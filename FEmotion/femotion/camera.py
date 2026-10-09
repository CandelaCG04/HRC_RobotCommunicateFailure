"""Webcam capture thread writing into a single-slot latest-frame buffer."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from femotion.config import CameraConfig
from femotion.metrics import RateMeter

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class Frame:
    image: np.ndarray  # BGR; never modified after capture
    seq: int
    t_capture: float  # time.monotonic()


class LatestFrame:
    """Holds only the newest frame. Older frames are overwritten (dropped), never queued."""

    def __init__(self):
        self._frame: Frame | None = None
        self._seq = 0
        self._cond = threading.Condition()

    def put(self, image: np.ndarray, t_capture: float) -> None:
        with self._cond:
            self._seq += 1
            self._frame = Frame(image, self._seq, t_capture)
            self._cond.notify_all()

    def get(self) -> Frame | None:
        with self._cond:
            return self._frame

    def wait_newer(self, last_seq: int, timeout: float) -> Frame | None:
        """Return the newest frame with ``seq > last_seq``, or None after ``timeout``."""
        with self._cond:
            if self._cond.wait_for(lambda: self._seq > last_seq, timeout):
                return self._frame
            return None


class CameraThread(threading.Thread):
    MAX_CONSECUTIVE_FAILURES = 30

    def __init__(self, cfg: CameraConfig, buffer: LatestFrame, meter: RateMeter, stop: threading.Event):
        super().__init__(name="camera", daemon=True)
        self.buffer, self.meter, self.stop_event = buffer, meter, stop
        self.error: Exception | None = None
        self._cap = cv2.VideoCapture(cfg.index, cv2.CAP_V4L2) if hasattr(cv2, "CAP_V4L2") else None
        if self._cap is None or not self._cap.isOpened():
            self._cap = cv2.VideoCapture(cfg.index)
        if not self._cap.isOpened():
            raise CameraError(f"Cannot open camera index {cfg.index}")
        if cfg.fourcc:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg.fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        self._cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        # No CAP_PROP_BUFFERSIZE=1: on V4L2 it caps throughput (~21 FPS measured). This thread
        # drains the driver continuously, so queued frames never become stale anyway.
        log.info(
            "camera %d opened: %dx%d @ %.0f FPS (requested %dx%d @ %d)",
            cfg.index,
            self._cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            self._cap.get(cv2.CAP_PROP_FPS),
            cfg.width, cfg.height, cfg.fps,
        )

    def run(self) -> None:
        failures = 0
        try:
            while not self.stop_event.is_set():
                ok, image = self._cap.read()  # allocates a fresh array each call
                if not ok:
                    failures += 1
                    if failures >= self.MAX_CONSECUTIVE_FAILURES:
                        raise CameraError("Camera stopped delivering frames")
                    time.sleep(0.01)
                    continue
                failures = 0
                now = time.monotonic()
                self.buffer.put(image, now)
                self.meter.tick(now)
        except Exception as exc:  # surfaced to the main thread
            self.error = exc
            self.stop_event.set()
        finally:
            self._cap.release()
