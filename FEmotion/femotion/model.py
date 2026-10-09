"""Pretrained emotion model: EmotiEffLib mbf_va_mtl, run with ONNX Runtime on the CPU.

Input  : RGB face, 112x112, (pixel / 255 - 0.5) / 0.5, NCHW.
Output : [N, 10] = 8 AffectNet logits (MODEL_CLASSES order) + valence + arousal.
"contempt" is not one of the central EMOTIONS; it is dropped and the rest renormalised.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from femotion.emotions import EMOTIONS
from femotion.preprocessing import prepare_faces

INPUT_SIZE = 112
MODEL_CLASSES = ("angry", "contempt", "disgust", "fear", "happy", "neutral", "sad", "surprise")
SOURCE = (
    "EmotiEffLib mbf_va_mtl.onnx (Apache-2.0), "
    "https://github.com/sb-ai-lab/EmotiEffLib/tree/main/models/affectnet_emotions/onnx. "
    "Run: python scripts/download_models.py"
)
_TO_EMOTIONS = [MODEL_CLASSES.index(e) for e in EMOTIONS]


class ModelLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmotionPrediction:
    probs: np.ndarray  # [len(EMOTIONS)] in EMOTIONS order
    label: str
    confidence: float
    valence: float  # about [-1, 1]
    arousal: float


def postprocess(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Raw [N, 10] outputs -> (probabilities in EMOTIONS order, valence/arousal [N, 2])."""
    n = len(MODEL_CLASSES)
    if raw.ndim != 2 or raw.shape[1] != n + 2:
        raise ModelLoadError(f"Unexpected model output shape {raw.shape}, expected [N, {n + 2}]")
    logits = raw[:, :n].astype(np.float64)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = e[:, _TO_EMOTIONS]
    return probs / probs.sum(axis=1, keepdims=True), raw[:, n:]


class EmotionModel:
    name = "mbf_va_mtl"
    crop_size = INPUT_SIZE

    def __init__(self, session, tta_flip: bool = False):
        self.session = session
        self.tta_flip = tta_flip
        self._input = session.get_inputs()[0].name

    def predict(self, face_bgr: np.ndarray) -> EmotionPrediction:
        return self.predict_batch([face_bgr])[0]

    def predict_batch(self, faces_bgr: list[np.ndarray]) -> list[EmotionPrediction]:
        if not faces_bgr:
            return []
        x = prepare_faces(faces_bgr, INPUT_SIZE)
        n = len(x)
        if self.tta_flip:  # also run the mirror image and average
            x = np.concatenate([x, np.ascontiguousarray(x[..., ::-1])])
        probs, va = postprocess(self.session.run(None, {self._input: x})[0])
        if self.tta_flip:
            probs, va = (probs[:n] + probs[n:]) / 2, (va[:n] + va[n:]) / 2
        out = []
        for p, (v, a) in zip(probs, va):
            i = int(p.argmax())
            out.append(EmotionPrediction(p, EMOTIONS[i], float(p[i]), float(v), float(a)))
        return out


def create_emotion_model(path: str | Path, threads: int = 2, tta_flip: bool = False) -> EmotionModel:
    """Load the emotion-trained ONNX model; fail clearly if it is missing or not the expected one."""
    path = Path(path)
    if not path.is_file():
        raise ModelLoadError(f"Emotion model not found at {path}.\nRequired: {SOURCE}")
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.log_severity_level = 3
    try:
        session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise ModelLoadError(f"Could not load {path}: {exc}") from exc
    if list(session.get_inputs()[0].shape[1:]) != [3, INPUT_SIZE, INPUT_SIZE]:
        raise ModelLoadError(f"{path} is not the expected model. Required: {SOURCE}")
    model = EmotionModel(session, tta_flip)
    model.predict(np.zeros((INPUT_SIZE, INPUT_SIZE, 3), np.uint8))  # validates the output layout
    return model
