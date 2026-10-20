"""
SentinelAI — Main Application Entry Point

Pipeline:
  Webcam / video / ESP32-CAM
    → YOLO11n + ByteTrack  (Tracker.update(frame))
    → Object State Manager
    → Deterministic Event Engine
    → Keyframe Evidence Capture
    → SQLite Event Database
    → Optional VLM Verification (async)
    → FastAPI + WebSocket Server  (background thread)
    → Dashboard  (http://localhost:8000)

Usage:
    # Webcam (default)
    python -m backend.main

    # Specific webcam index
    python -m backend.main --source 1

    # Video file (loops for demo)
    python -m backend.main --source path/to/video.mp4 --loop

    # ESP32-CAM MJPEG stream
    python -m backend.main --source http://192.168.1.100/stream

    # Headless / server mode
    python -m backend.main --no-display

    # Skip VLM loading (faster startup)
    python -m backend.main --no-vlm

Press Q in the display window (or Ctrl+C) to quit.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import json
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2

from backend.camera.camera import CameraError, CameraSource
from backend.config.settings import get_settings
from backend.database.event_database import EventDatabase
from backend.event_engine.event_engine import EventEngine
from backend.evidence.keyframe_capture import KeyframeCapture
from backend.retrival.retrival import EventRetriever
from backend.state_manager.state_manager import StateManager
from backend.tracker.tracker import Tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel.main")


# ---------------------------------------------------------------------------
# FPS counter
# ---------------------------------------------------------------------------

class FPSCounter:
    def __init__(self, window: int = 30) -> None:
        self._times: list[float] = []
        self._window = window

    def tick(self) -> float:
        now = time.monotonic()
        self._times.append(now)
        if len(self._times) > self._window:
            self._times.pop(0)
        if len(self._times) < 2:
            return 0.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])


# ---------------------------------------------------------------------------
# API server thread
# ---------------------------------------------------------------------------

def _start_api_server(host: str, port: int, control: dict) -> None:
    """Launch uvicorn in a background daemon thread."""
    import uvicorn
    from backend.api.websocket import set_event_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    set_event_loop(loop)

    config = uvicorn.Config(
        "backend.api:app",
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    control["server"] = server

    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

_EVENT_COLORS = {
    "UNATTENDED_OBJECT": (0, 0, 255),
    "LOITERING":         (0, 0, 255),
    "RUNNING":           (255, 128, 0),
    "PERSON_ENTERED":    (0, 200, 0),
    "PERSON_EXITED":     (0, 200, 0),
    "ZONE_CHANGED":      (200, 200, 0),
}
_DEFAULT_COLOR = (0, 255, 0)


def _draw_tracks(frame, tracks, states) -> None:
    state_map = {s.track_id: s for s in states}
    for track in tracks:
        box   = track.bounding_box
        state = state_map.get(track.track_id)

        if state and getattr(state, "unattended", False):
            color = _EVENT_COLORS["UNATTENDED_OBJECT"]
            label = f"UNATTENDED | {track.class_name} #{track.track_id}"
        elif state and getattr(state, "loitering", False):
            color = _EVENT_COLORS["LOITERING"]
            label = f"LOITERING | {track.class_name} #{track.track_id}"
        elif state and getattr(state, "running", False):
            color = _EVENT_COLORS["RUNNING"]
            label = f"RUNNING | {track.class_name} #{track.track_id}"
        else:
            color = _DEFAULT_COLOR
            label = f"{track.class_name} #{track.track_id}"

        x1, y1, x2, y2 = int(box.x1), int(box.y1), int(box.x2), int(box.y2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(y1 - 8, 16)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def _draw_hud(frame, fps: float, event_count: int, track_count: int) -> None:
    h = frame.shape[0]
    cv2.rectangle(frame, (0, h - 40), (380, h), (20, 20, 20), -1)
    cv2.putText(
        frame,
        f"SentinelAI  FPS:{fps:.1f}  Tracks:{track_count}  Events:{event_count}",
        (8, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    cfg = get_settings()

    # ---- Database ----
    db = EventDatabase(database_path=str(cfg.resolve_path(cfg.database.path)))
    retriever = EventRetriever(db)

    # ---- Evidence ----
    evidence = KeyframeCapture(output_dir=str(cfg.resolve_path(cfg.evidence.output_dir)))

    # Model loading happens in managed local workers, independently of capture.
    if args.vlm_enabled is not None:
        cfg.vlm.enabled = args.vlm_enabled
    if args.llm_enabled is not None:
        cfg.llm.enabled = args.llm_enabled
    from backend.ai_runtime.manager import AIManager
    ai = AIManager(cfg, db)
    ai.start()
    event_verifier = ai  # existing cleanup paths stop both managed model workers
    llm = ai.llm

    # ---- Wire API shared state ----
    from backend.api import routes as api_routes
    api_routes.set_shared_state(db=db, retriever=retriever, llm=llm, ai=ai)
    api_routes.update_live_state(
        model_loaded=False,
        vlm_loaded=False,
        pipeline_status="starting",
        vlm_adapter_loaded=(
            event_verifier is not None
            and hasattr(event_verifier, "_verifier")
            and getattr(event_verifier._verifier, "adapter_loaded", False)
        ),
    )

    # ---- API server thread ----
    api_control = {}
    api_thread = threading.Thread(
        target=_start_api_server,
        args=(cfg.api.host, cfg.api.port, api_control),
        daemon=True,
        name="api-server",
    )
    api_thread.start()
    logger.info("API server starting at http://%s:%d", cfg.api.host, cfg.api.port)
    time.sleep(1.0)  # give uvicorn a moment to bind

    device = None
    if cfg.esp32.enabled and cfg.esp32.mode == "serial":
        from backend.esp32.serial_device import SerialDevice
        device = SerialDevice(cfg.esp32.serial_port, cfg.esp32.baudrate,
                              lambda **values: api_routes.update_live_state(**values))
        device.start()

    # ---- Detection / Tracking / State / Events ----
    try:
        tracker = Tracker(
            model_path=str(cfg.resolve_path(cfg.detector.model_path)),
            confidence_threshold=cfg.detector.confidence_threshold,
            iou_threshold=cfg.detector.iou_threshold,
            device=cfg.detector.device,
        )
    except Exception as exc:
        logger.error("Detector initialization failed: %s", exc)
        api_routes.update_live_state(camera_ok=False, pipeline_status="model_error", last_error=str(exc))
        if device is not None:
            device.stop()
        if event_verifier is not None:
            event_verifier.stop()
        if "server" in api_control:
            api_control["server"].should_exit = True
        api_thread.join(timeout=5)
        api_routes.set_shared_state(None, None)
        db.close()
        return 1
    api_routes.update_live_state(model_loaded=True, tracker_status="loading")
    state_mgr = StateManager(missing_timeout=cfg.event_engine.missing_timeout_s)
    event_eng = EventEngine()

    # Apply event engine thresholds from config
    eng_cfg = cfg.event_engine
    from backend.event_engine.zone import Zone
    event_eng.zones = [Zone(z.name, z.x1, z.y1, z.x2, z.y2) for z in eng_cfg.zones]
    event_eng.missing_timeout = eng_cfg.missing_timeout_s
    event_eng.loitering_threshold = eng_cfg.loitering_threshold_s
    event_eng.running_threshold   = eng_cfg.running_speed_px_per_frame
    event_eng.association_distance = eng_cfg.association_distance_px
    event_eng.separation_distance  = eng_cfg.separation_distance_px
    event_eng.unattended_threshold = eng_cfg.unattended_threshold_s
    api_routes.update_live_state(event_engine_status="ready")

    # ---- Camera ----
    source = args.source if args.source is not None else (cfg.esp32.stream_url if cfg.esp32.enabled and cfg.esp32.mode == "stream" else cfg.camera.source)
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    elif isinstance(source, str) and not source.startswith(("http://", "https://", "rtsp://")):
        source = str(cfg.resolve_path(source))

    camera = CameraSource(
        source=source,
        width=cfg.camera.width,
        height=cfg.camera.height,
        fps=cfg.camera.fps,
        max_failures=cfg.camera.max_read_failures,
        reconnect_delay_s=cfg.camera.reconnect_delay_s,
        loop_video=args.loop,
    )

    fps_counter = FPSCounter()
    total_events = 0

    # ---- Graceful shutdown ----
    _stop = threading.Event()

    def _signal_handler(*_):
        _stop.set()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Opening camera source: %r", source)

    try:
        camera.open()
    except CameraError as exc:
        logger.error("Cannot open camera: %s", exc)
        api_routes.update_live_state(camera_ok=False, pipeline_status="source_error", last_error=str(exc))
        if device is not None:
            device.stop()
        if event_verifier is not None:
            event_verifier.stop()
        if "server" in api_control:
            api_control["server"].should_exit = True
        api_thread.join(timeout=5)
        api_routes.set_shared_state(None, None)
        db.close()
        return 1

    api_routes.update_live_state(camera_ok=True, pipeline_status="running", source=str(source),
        source_kind="webcam" if isinstance(source,int) else "video_file" if camera.is_file else "network_stream",
        esp32_camera_verified=False)
    from backend.api.websocket import push_frame

    logger.info("Detection loop running. Press Q in the window (or Ctrl+C) to quit.")

    started_at = time.monotonic()
    video_origin = datetime.now(timezone.utc)
    frames_processed = 0
    trace = None
    if args.trace:
        trace_path = cfg.resolve_path(args.trace)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace = trace_path.open("w", encoding="utf-8")
    continuity_lost = False
    last_media_time = -1.0
    media_offset = 0.0
    try:
        while not _stop.is_set():
            if args.max_frames and frames_processed >= args.max_frames:
                break
            if args.max_seconds and time.monotonic() - started_at >= args.max_seconds:
                break
            ok, frame = camera.read_frame()
            if not ok:
                continuity_lost = True
                api_routes.update_live_state(camera_ok=False, pipeline_status="reconnecting", fps=0, track_count=0)
                if camera.is_file:
                    logger.info("Camera stream ended.")
                    break
                continue  # transient failure — keep looping

            if continuity_lost:
                tracker.reset()
                state_mgr.states.clear()
                event_eng.reset()
                continuity_lost = False
            api_routes.update_live_state(camera_ok=True, pipeline_status="running", last_error=None)
            if camera.is_file:
                media_time = camera.position_seconds
                if media_time < last_media_time:
                    media_offset += last_media_time + 1.0 / cfg.camera.fps
                    tracker.reset()
                    state_mgr.states.clear()
                    event_eng.reset()
                    logger.info("Video rewind: reset tracking and temporal state for new segment")
                last_media_time = media_time
                timestamp = video_origin + timedelta(seconds=media_offset + media_time)
            else:
                timestamp = datetime.now(timezone.utc)
            frames_processed += 1

            # ---- Detect + Track (single YOLO call with ByteTrack) ----
            try:
                tracks = tracker.update(frame)
            except Exception as exc:
                logger.warning("Tracker error (skipping frame): %s", exc)
                continuity_lost = True
                api_routes.update_live_state(pipeline_status="inference_error", tracker_status="error", last_error=str(exc))
                continue

            # ---- State + Events ----
            states = state_mgr.update(tracks, timestamp)
            events = event_eng.update(states, timestamp)

            fps = fps_counter.tick()

            # ---- Persist events + capture evidence ----
            persisted_events = []
            for event in events:
                try:
                    evidence_path = evidence.save(
                        frame, event.event_type, event.track_id, timestamp
                    )
                except Exception as exc:
                    logger.warning("Evidence capture failed: %s", exc)
                    evidence_path = None

                event_id = db.save_event(event, evidence_path)
                total_events += 1
                persisted_events.append(retriever.get_by_id(event_id))
                if device is not None:
                    device.alert(event.event_type)

                logger.info(
                    "EVENT #%d: %s | track=%d | zone=%s | desc=%s",
                    event_id, event.event_type, event.track_id,
                    event.zone, event.description,
                )

                ai.enqueue_event(
                    event_id=event_id,event_type=event.event_type,
                    evidence_path=evidence_path,class_name=event.class_name,zone=event.zone)

            # ---- Push to WebSocket dashboard ----
            track_dicts = [
                {
                    "track_id":   t.track_id,
                    "class_name": t.class_name,
                    "confidence": round(t.confidence, 3),
                    "box": [
                        int(t.bounding_box.x1), int(t.bounding_box.y1),
                        int(t.bounding_box.x2), int(t.bounding_box.y2),
                    ],
                    "zone": next((s.current_zone for s in states if s.track_id == t.track_id), None),
                }
                for t in tracks
            ]
            event_dicts = persisted_events
            if trace is not None:
                trace.write(json.dumps(dict(frame=frames_processed, timestamp=timestamp.isoformat(), tracks=track_dicts, events=event_dicts, fps=fps)) + "\n")
                trace.flush()
            push_frame(
                tracks=track_dicts,
                events=event_dicts,
                fps=fps,
                timestamp=timestamp.isoformat(),
            )

            api_routes.update_live_state(
                fps=fps,
                track_count=len(tracks),
                active_event_types=[e.event_type for e in events],
                frame_width=frame.shape[1], frame_height=frame.shape[0],
                frames_processed=frames_processed,tracker_status="ready",
            )

            if frames_processed % 3 == 1:
                preview = frame.copy()
                _draw_tracks(preview, tracks, states)
                ok_jpg, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok_jpg:
                    api_routes.update_preview(encoded.tobytes())

            # ---- OpenCV display ----
            if not args.no_display:
                _draw_tracks(frame, tracks, states)
                _draw_hud(frame, fps, total_events, len(tracks))
                cv2.imshow("SentinelAI", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    break

    except CameraError as exc:
        logger.error("Camera error: %s", exc)
        api_routes.update_live_state(camera_ok=False, pipeline_status="source_error", last_error=str(exc))
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        if trace is not None:
            trace.close()
        api_routes.update_live_state(camera_ok=False, pipeline_status="stopped", fps=0, track_count=0)
        if device is not None:
            device.stop()
        if event_verifier is not None:
            event_verifier.stop()
        if "server" in api_control:
            api_control["server"].should_exit = True
        api_thread.join(timeout=5)
        api_routes.set_shared_state(None, None)
        db.close()
        if not args.no_display:
            cv2.destroyAllWindows()
        logger.info(
            "SentinelAI shut down cleanly. Total events recorded: %d",
            total_events,
        )

    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SentinelAI — autonomous edge intelligence pipeline"
    )
    p.add_argument(
        "--source",
        default=None,
        help=(
            "Camera source: webcam index (0, 1 …), "
            "video file path, or ESP32-CAM MJPEG URL. Default: 0."
        ),
    )
    p.add_argument(
        "--loop",
        action="store_true",
        help="Loop video file continuously (demo mode).",
    )
    p.add_argument(
        "--no-display",
        action="store_true",
        help="Disable the OpenCV preview window (headless / server mode).",
    )
    vlm_flags = p.add_mutually_exclusive_group()
    vlm_flags.add_argument("--vlm",dest="vlm_enabled",action="store_true",help="Enable local Florence verification.")
    vlm_flags.add_argument("--no-vlm",dest="vlm_enabled",action="store_false",help="Disable Florence verification.")
    llm_flags = p.add_mutually_exclusive_group()
    llm_flags.add_argument("--llm",dest="llm_enabled",action="store_true",help="Enable direct local Hugging Face QA.")
    llm_flags.add_argument("--no-llm",dest="llm_enabled",action="store_false",help="Disable local LLM QA.")
    p.set_defaults(vlm_enabled=None,llm_enabled=None)
    p.add_argument(
        "--config",
        default=None,
        help="Path to a custom config.yaml file.",
    )
    p.add_argument("--max-frames", type=int, default=0, help="Stop after N processed frames (0 = unlimited).")
    p.add_argument("--max-seconds", type=float, default=0, help="Stop after elapsed seconds (0 = unlimited).")
    p.add_argument("--trace", default=None, help="Optional JSONL per-frame audit output.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.config:
        from backend.config.settings import reset_settings
        reset_settings()
        get_settings(config_path=args.config)

    sys.exit(run(args))