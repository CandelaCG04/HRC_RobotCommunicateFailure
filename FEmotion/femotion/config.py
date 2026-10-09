"""Application configuration: dataclasses with defaults, optionally overridden by YAML."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    fourcc: str | None = "MJPG"  # many webcams only reach 30 FPS with MJPG; None = driver default


@dataclass
class DetectorConfig:
    model_path: str = "models/face_detection_yunet_2023mar.onnx"
    rate_hz: float = 10.0
    score_threshold: float = 0.7
    nms_threshold: float = 0.3
    min_face_size: int = 40  # pixels; smaller faces are ignored


@dataclass
class TrackerConfig:
    iou_threshold: float = 0.3
    min_hits: int = 2  # detections before a track is confirmed and classified
    timeout_s: float = 1.0  # unmatched tracks are dropped after this


@dataclass
class ModelConfig:
    path: str = "models/mbf_va_mtl.onnx"
    rate_hz: float = 15.0
    threads: int = 2  # ONNX Runtime CPU threads
    face_margin: float = 0.1  # fraction of the box size added on each side before cropping
    tta_flip: bool = True  # average predictions over the face and its mirror image
    max_yaw: float = 0.45  # skip faces turned further than this (0 = frontal, ~0.5 = profile)


@dataclass
class MeshConfig:
    enabled: bool = True
    model_path: str = "models/face_landmarker.task"
    rate_hz: float = 15.0
    max_faces: int = 2
    match_iou: float = 0.3  # min IoU between a mesh face and a tracked face to associate them


def _default_frustration_weights() -> dict[str, float]:
    return {
        "neg_valence": 0.25,
        "arousal": 0.10,
        "neg_emotions": 0.15,
        "brow_lower": 0.25,
        "squint": 0.10,
        "lip_press": 0.10,
        "dimple": 0.05,
    }


@dataclass
class FrustrationConfig:
    enabled: bool = True
    weights: dict[str, float] = field(default_factory=_default_frustration_weights)
    blendshape_scale: float = 0.3  # blendshape increase over baseline that counts as fully active
    baseline_tau_s: float = 20.0  # per-face resting baseline (updated while neutral)
    warmup_s: float = 3.0  # baseline-only period after a face appears; no score yet
    score_tau_ms: float = 500.0  # EMA on the frustration score
    on_threshold: float = 0.5
    off_threshold: float = 0.35
    hold_on_ms: float = 1500.0
    hold_off_ms: float = 1000.0


@dataclass
class StabilityConfig:
    min_raw_confidence: float = 0.35  # raw predictions below this are discarded
    smoothing_tau_ms: float = 300.0  # EMA time constant
    min_state_confidence: float = 0.4  # smoothed confidence needed to become a candidate
    hold_ms: float = 200.0  # candidate must persist this long to become the stable state


@dataclass
class DatabaseConfig:
    path: str = "femotion.db"


@dataclass
class DisplayConfig:
    show_window: bool = False
    metrics_log_interval_s: float = 5.0


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    mesh: MeshConfig = field(default_factory=MeshConfig)
    frustration: FrustrationConfig = field(default_factory=FrustrationConfig)
    stability: StabilityConfig = field(default_factory=StabilityConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


def _apply(obj: Any, data: dict, where: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown config key '{where}{key}'")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"Config section '{where}{key}' must be a mapping")
            _apply(current, value, f"{where}{key}.")
        else:
            setattr(obj, key, value)


def resolve_path(path: str | Path, base: Path = PROJECT_ROOT) -> Path:
    """Resolve a config path relative to ``base`` (the config file's directory)."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else (base / p)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load defaults, then override with the YAML file at ``path`` (if given).

    Relative file paths in the config are resolved against the config file's directory
    (or the project root when no file is given).
    """
    cfg = AppConfig()
    base = PROJECT_ROOT
    if path is not None:
        path = Path(path)
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top level must be a mapping")
        _apply(cfg, data, "")
        base = path.resolve().parent

    cfg.detector.model_path = str(resolve_path(cfg.detector.model_path, base))
    cfg.database.path = str(resolve_path(cfg.database.path, base))
    cfg.mesh.model_path = str(resolve_path(cfg.mesh.model_path, base))
    cfg.model.path = str(resolve_path(cfg.model.path, base))
    return cfg
