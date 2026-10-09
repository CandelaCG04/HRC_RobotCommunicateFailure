# FEmotion

Real-time facial emotion and frustration recognition from a laptop webcam, on the CPU, using pretrained models. Emotion and frustration state changes are logged to SQLite.

## Setup

Requires Python 3.10+ and a webcam.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_models.py   # downloads the 3 model files into models/
```

## Run

```bash
.venv/bin/python -m femotion                  # headless; Ctrl-C to stop
.venv/bin/python -m femotion --show           # with OpenCV debug window; q / Esc to quit
.venv/bin/python -m femotion --duration 30    # stop after 30 s
.venv/bin/pytest -q                           # tests
```

All settings are in `config.yaml`: camera, rates, stability, frustration weights and thresholds.

Results go to `femotion.db`, one row per state change:

```bash
sqlite3 femotion.db "select face_id, kind, timestamp, previous_emotion, emotion, confidence, duration_ms from emotion_events"
```

- `kind` is `emotion` or `frustration`.
- `timestamp` (UTC) is when the new state began.
- `duration_ms` is how long the previous state lasted.
- `emotion = NULL` means the state ended: the face was lost, the session ended, or frustration stopped.

## Project tree

```
config.yaml                 all settings
requirements.txt
scripts/download_models.py  fetches the pretrained models
models/                     downloaded model files (not in git)
femotion/
  __main__.py               entry point (CLI, display loop)
  pipeline.py               camera thread -> worker: detect, track, classify, stabilise, log
  camera.py                 webcam capture into a latest-frame buffer
  detection.py              YuNet face detector (box + 5 landmarks)
  tracking.py               IoU tracker -> session-local face_id
  preprocessing.py          eye-levelled face crop, head-yaw estimate, model input
  model.py                  mbf_va_mtl emotion model (ONNX Runtime)
  emotions.py               the 7 emotion classes
  smoothing.py, state.py    EMA smoothing and emotion state machine
  face_mesh.py              MediaPipe blendshapes (frustration features)
  frustration.py            frustration score and state machine
  db.py                     SQLite sessions and transitions
  metrics.py, visualize.py  FPS/latency meters, optional overlay
  config.py                 config dataclasses + YAML loading
tests/
```

## Models

| File | Role | Spec |
|---|---|---|
| `mbf_va_mtl.onnx` | Emotion model, from [EmotiEffLib](https://github.com/sb-ai-lab/EmotiEffLib) (Apache-2.0) | MobileFaceNet trained on AffectNet. Input: RGB face 112×112, `(pixel/255 − 0.5)/0.5`. Output: 8 emotion logits (anger, contempt, disgust, fear, happiness, neutral, sadness, surprise) plus valence and arousal. "Contempt" is dropped, giving 7 classes: angry, disgust, fear, happy, sad, surprise, neutral. ~7 ms per face on CPU (~12.5 ms with mirror averaging). |
| `face_detection_yunet_2023mar.onnx` | Face detector, [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT) | Face box plus 5 landmarks, used for eye alignment and head-yaw gating. ~8 ms per frame at 10 Hz. |
| `face_landmarker.task` | [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) (Apache-2.0) | 478 landmarks and 52 blendshapes. Brow-lower, squint, lip-press and dimple feed the frustration score. ~12 ms per call at 15 Hz. |

**Frustration** is not a model class. It is a configurable, **uncalibrated** heuristic:

- The score is a weighted mean of negative valence, arousal (counted only while valence is negative), angry+disgust+sad probability, and blendshape rises above each person's resting baseline.
- The state starts after the score stays above `on_threshold` for `hold_on_ms`, and ends after it stays below `off_threshold` for `hold_off_ms`.
- Tune the weights and thresholds in `config.yaml`.
