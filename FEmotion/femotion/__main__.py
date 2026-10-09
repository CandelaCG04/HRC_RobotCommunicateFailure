"""Entry point: ``python -m femotion [--config config.yaml] [--show] [--duration S]``."""
from __future__ import annotations

import argparse
import logging
import sys
import time

from femotion.config import PROJECT_ROOT, load_config

log = logging.getLogger("femotion")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-time facial emotion and frustration recognition")
    default_cfg = PROJECT_ROOT / "config.yaml"
    parser.add_argument("--config", default=str(default_cfg) if default_cfg.exists() else None)
    parser.add_argument("--show", action="store_true", help="show the OpenCV debug window")
    parser.add_argument("--duration", type=float, default=None, help="stop after this many seconds")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.show:
        cfg.display.show_window = True

    # Heavy imports after argument parsing so --help stays fast.
    import cv2

    from femotion.camera import CameraError
    from femotion.detection import DetectorModelNotFoundError, FaceDetector
    from femotion.face_mesh import FaceMesh, MeshModelNotFoundError
    from femotion.model import ModelLoadError, create_emotion_model
    from femotion.pipeline import Pipeline
    from femotion.visualize import draw_overlay

    try:
        model = create_emotion_model(cfg.model.path, cfg.model.threads, cfg.model.tta_flip)
        detector = FaceDetector(cfg.detector)
        mesh = None
        if cfg.mesh.enabled and cfg.frustration.enabled:
            try:
                mesh = FaceMesh(cfg.mesh)
            except MeshModelNotFoundError as exc:
                log.warning("%s -- frustration will use the emotion model's signals only", exc)
        pipeline = Pipeline(cfg, detector, model, mesh)
    except (ModelLoadError, DetectorModelNotFoundError, CameraError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    log.info(
        "model %s loaded (tta_flip=%s); face mesh=%s; frustration=%s; show_window=%s",
        model.name, cfg.model.tta_flip, mesh is not None, cfg.frustration.enabled, cfg.display.show_window,
    )

    window = "FEmotion"
    pipeline.start()
    start = last_metrics = time.monotonic()
    try:
        while not pipeline.stop_event.is_set():
            now = time.monotonic()
            if args.duration is not None and now - start >= args.duration:
                break
            if now - last_metrics >= cfg.display.metrics_log_interval_s:
                log.info(pipeline.meters.summary())
                last_metrics = now
            if cfg.display.show_window:
                frame = pipeline.frames.get()
                if frame is not None:
                    cv2.imshow(window, draw_overlay(frame.image, pipeline.snapshot, pipeline.meters.summary()))
                if cv2.waitKey(30) & 0xFF in (ord("q"), 27):
                    break
            else:
                pipeline.stop_event.wait(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("shutting down: %s", pipeline.meters.summary())
        pipeline.stop()
        if mesh is not None:
            mesh.close()
        if cfg.display.show_window:
            cv2.destroyAllWindows()

    if pipeline.error:
        print(f"ERROR: {pipeline.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
