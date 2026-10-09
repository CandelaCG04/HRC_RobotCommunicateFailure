"""Real-time pipeline: camera thread -> worker thread (detect/track/classify/stabilise/log)."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Protocol

import numpy as np

from femotion.camera import CameraThread, Frame, LatestFrame
from femotion.config import AppConfig
from femotion.db import EventLogger, utc_now
from femotion.metrics import LatencyMeter, RateMeter
from femotion.frustration import FrustrationEstimator, FrustrationStateMachine
from femotion.model import EmotionPrediction
from femotion.preprocessing import align_face, yaw_proxy
from femotion.smoothing import ProbabilityEMA
from femotion.state import EmotionStateMachine, Transition
from femotion.tracking import Box, IoUTracker, Track

log = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Box]: ...


class Classifier(Protocol):
    name: str
    crop_size: int  # side of the face crop to pass to predict_batch

    def predict_batch(self, faces_bgr: list[np.ndarray]) -> list[EmotionPrediction]: ...


class Mesh(Protocol):
    def process(self, frame: np.ndarray, t: float, tracks: list[Track]) -> dict[int, dict[str, float]]: ...


@dataclass(frozen=True)
class FaceResult:
    face_id: int
    box: Box
    emotion: str | None  # stable emotion (None until one is established)
    confidence: float | None
    frustration: float | None = None  # score in [0, 1]; None while warming up / disabled
    frustrated: bool = False


@dataclass(frozen=True)
class Snapshot:
    frame_seq: int = 0
    faces: tuple[FaceResult, ...] = ()


@dataclass
class Meters:
    camera: RateMeter = field(default_factory=RateMeter)
    detection: RateMeter = field(default_factory=RateMeter)
    inference: RateMeter = field(default_factory=RateMeter)
    mesh: RateMeter = field(default_factory=RateMeter)
    latency: LatencyMeter = field(default_factory=LatencyMeter)
    mesh_time: LatencyMeter = field(default_factory=LatencyMeter)  # CPU time per mesh call

    def summary(self) -> str:
        lat, mesh_ms = self.latency.mean_ms(), self.mesh_time.mean_ms()
        return (
            f"camera {self.camera.rate():.1f} FPS | detection {self.detection.rate():.1f} FPS | "
            f"emotion {self.inference.rate():.1f} FPS | mesh {self.mesh.rate():.1f} FPS"
            + (f" ({mesh_ms:.1f} ms)" if mesh_ms is not None else "")
            + " | latency " + (f"{lat:.0f} ms" if lat is not None else "n/a")
        )


def _next_due(due: float, period: float, now: float) -> float:
    """Keep a fixed cadence when slightly late (so the average rate matches the target
    despite frame-interval granularity); restart the cadence when far behind."""
    return due + period if now - due < period else now + period


class _Face:
    def __init__(self, face_id: int, cfg: AppConfig, t0: float):
        s, f = cfg.stability, cfg.frustration
        self.ema = ProbabilityEMA(s.smoothing_tau_ms / 1000)
        self.state = EmotionStateMachine(face_id, s.min_state_confidence, s.hold_ms / 1000)
        self.frustration = FrustrationEstimator(f, t0) if f.enabled else None
        self.frustration_state = FrustrationStateMachine(
            face_id, f.on_threshold, f.off_threshold, f.hold_on_ms / 1000, f.hold_off_ms / 1000
        )


class FrameProcessor:
    """Synchronous per-frame logic, rate-limited internally. Used by the worker thread
    (and directly by tests)."""

    def __init__(
        self,
        cfg: AppConfig,
        detector: Detector,
        model: Classifier,
        logger: EventLogger,
        meters: Meters,
        clock: Callable[[], float] = time.monotonic,
        mesh: Mesh | None = None,
    ):
        self.cfg, self.detector, self.model, self.logger, self.meters = cfg, detector, model, logger, meters
        self.clock = clock
        self.mesh = mesh
        t = cfg.tracker
        self.tracker = IoUTracker(t.iou_threshold, t.min_hits, t.timeout_s)
        self._faces: dict[int, _Face] = {}
        self._blendshapes: dict[int, tuple[float, dict[str, float]]] = {}  # face_id -> (t, scores)
        self._detect_period = 1.0 / cfg.detector.rate_hz
        self._infer_period = 1.0 / cfg.model.rate_hz
        self._mesh_period = 1.0 / cfg.mesh.rate_hz
        self._next_detect = float("-inf")
        self._next_infer = float("-inf")
        self._next_mesh = float("-inf")

    def process(self, frame: Frame) -> Snapshot:
        now = self.clock()
        if now >= self._next_detect:
            self._next_detect = _next_due(self._next_detect, self._detect_period, now)
            boxes = self.detector.detect(frame.image)
            self.meters.detection.tick(now)
            for track in self.tracker.update(boxes, frame.t_capture):
                self._close_face(track.face_id, track.last_seen)

        if self.mesh is not None and now >= self._next_mesh:
            self._next_mesh = _next_due(self._next_mesh, self._mesh_period, now)
            self._run_mesh(frame)

        if now >= self._next_infer:
            self._next_infer = _next_due(self._next_infer, self._infer_period, now)
            self._classify(frame)

        return Snapshot(frame.seq, tuple(self._face_result(t) for t in self.tracker.confirmed()))

    def close(self) -> None:
        """Close all open emotion states (session end)."""
        for track in self.tracker.tracks:
            self._close_face(track.face_id, track.last_seen)

    def _fresh_tracks(self, frame: Frame) -> list[Track]:
        # Skip stale boxes (face not re-detected recently) so background is never analysed.
        return [
            t for t in self.tracker.confirmed()
            if frame.t_capture - t.last_seen <= 2 * self._detect_period
        ]

    def _run_mesh(self, frame: Frame) -> None:
        tracks = self._fresh_tracks(frame)
        if not tracks:
            return
        start = time.perf_counter()
        shapes = self.mesh.process(frame.image, frame.t_capture, tracks)
        self.meters.mesh_time.add(time.perf_counter() - start)
        self.meters.mesh.tick(self.clock())
        for face_id, scores in shapes.items():
            self._blendshapes[face_id] = (frame.t_capture, scores)

    def _face_crop(self, frame: Frame, track: Track) -> np.ndarray | None:
        mc = self.cfg.model
        yaw = yaw_proxy(track.box)
        if yaw is not None and yaw > mc.max_yaw:
            return None  # face turned too far for a reliable expression reading
        return align_face(frame.image, track.box, mc.face_margin, self.model.crop_size)

    def _classify(self, frame: Frame) -> None:
        tracks, crops = [], []
        for track in self._fresh_tracks(frame):
            crop = self._face_crop(frame, track)
            if crop is not None:
                tracks.append(track)
                crops.append(crop)
        if not crops:
            return

        preds = self.model.predict_batch(crops)
        self.meters.inference.tick(self.clock())
        min_raw = self.cfg.stability.min_raw_confidence
        t = frame.t_capture
        for track, pred in zip(tracks, preds):
            face = self._faces.get(track.face_id)
            if face is None:
                face = self._faces[track.face_id] = _Face(track.face_id, self.cfg, t)
            if pred.confidence < min_raw:
                continue  # confidence filter: discard unreliable raw predictions
            smoothed = face.ema.update(pred.probs, t)
            transition = face.state.update(smoothed, t)
            if transition:
                self._log(transition)
            if face.frustration is not None:
                score = face.frustration.update(
                    t, smoothed, pred.valence, pred.arousal,
                    self._recent_blendshapes(track.face_id, t), face.state.stable,
                )
                transition = face.frustration_state.update(score, t)
                if transition:
                    self._log(transition, kind="frustration")
        self.meters.latency.add(self.clock() - frame.t_capture)

    def _recent_blendshapes(self, face_id: int, t: float) -> dict[str, float] | None:
        entry = self._blendshapes.get(face_id)
        if entry is None or t - entry[0] > 2 * self._mesh_period:
            return None
        return entry[1]

    def _face_result(self, track) -> FaceResult:
        face = self._faces.get(track.face_id)
        if face is None:
            return FaceResult(track.face_id, track.box, None, None)
        return FaceResult(
            track.face_id, track.box, face.state.stable, face.state.stable_confidence,
            face.frustration.score if face.frustration else None, face.frustration_state.active,
        )

    def _close_face(self, face_id: int, t: float) -> None:
        self._blendshapes.pop(face_id, None)
        face = self._faces.pop(face_id, None)
        if face is not None:
            transition = face.state.close(t)
            if transition:
                self._log(transition)
            transition = face.frustration_state.close(t)
            if transition:
                self._log(transition, kind="frustration")

    def _log(self, tr: Transition, kind: str = "emotion") -> None:
        # Convert the monotonic onset time to an aware UTC wall-clock timestamp.
        timestamp = utc_now() - timedelta(seconds=max(0.0, self.clock() - tr.t))
        log.info(
            "face %d [%s]: %s -> %s (conf %s, previous lasted %s ms)",
            tr.face_id, kind, tr.previous, tr.emotion,
            f"{tr.confidence:.2f}" if tr.confidence is not None else "-", tr.duration_ms,
        )
        self.logger.log_transition(
            tr.face_id, timestamp, tr.previous, tr.emotion, tr.confidence, tr.duration_ms, kind
        )


class Pipeline:
    """Owns the camera and worker threads. The display (if any) only reads ``frames``
    and ``snapshot`` and never blocks processing."""

    def __init__(self, cfg: AppConfig, detector: Detector, model: Classifier, mesh: Mesh | None = None):
        self.cfg, self.detector, self.model, self.mesh = cfg, detector, model, mesh
        self.frames = LatestFrame()
        self.meters = Meters()
        self.stop_event = threading.Event()
        self._snapshot = Snapshot()
        self._snap_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_worker, name="worker", daemon=True)
        self._worker_error: Exception | None = None
        self._camera = CameraThread(cfg.camera, self.frames, self.meters.camera, self.stop_event)

    @property
    def snapshot(self) -> Snapshot:
        with self._snap_lock:
            return self._snapshot

    @property
    def error(self) -> Exception | None:
        return self._camera.error or self._worker_error

    def start(self) -> None:
        self._camera.start()
        self._worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._worker.join(timeout=5)
        self._camera.join(timeout=5)

    def _run_worker(self) -> None:
        logger = EventLogger(self.cfg.database.path)  # created in, and used only by, this thread
        processor = None
        try:
            session = logger.start_session(self.cfg.camera.index, self.model.name)
            log.info("session %d started (db: %s)", session, self.cfg.database.path)
            processor = FrameProcessor(
                self.cfg, self.detector, self.model, logger, self.meters, mesh=self.mesh
            )
            last_seq = 0
            while not self.stop_event.is_set():
                frame = self.frames.wait_newer(last_seq, timeout=0.5)
                if frame is None:
                    continue
                last_seq = frame.seq
                snapshot = processor.process(frame)
                with self._snap_lock:
                    self._snapshot = snapshot
        except Exception as exc:
            log.exception("worker failed")
            self._worker_error = exc
            self.stop_event.set()
        finally:
            if processor is not None:
                processor.close()
            logger.end_session()
            logger.close()
            log.info("session closed")
