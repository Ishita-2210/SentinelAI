"""
SentinelAI — Central Configuration

Loads from config.yaml in the project root if present; otherwise uses
built-in defaults. Every setting is overridable via the YAML file so
the system can be reconfigured without touching source code.

Usage:
    from backend.config.settings import get_settings

    cfg = get_settings()
    print(cfg.camera.source)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sub-config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CameraConfig:
    """Camera source and capture parameters."""
    # Webcam index (0, 1, …) or MJPEG stream URL for ESP32-CAM.
    source: int | str = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    # Number of consecutive failed reads before raising CameraError.
    max_read_failures: int = 10
    reconnect_delay_s: float = 2.0


@dataclass
class DetectorConfig:
    """YOLO object detector settings."""
    model_path: str = "yolo11n.pt"
    confidence_threshold: float = 0.5
    iou_threshold: float = 0.7
    # Device: "cpu", "cuda", "auto"
    device: str = "auto"


@dataclass
class ZoneDefinition:
    """A named rectangular zone in pixel-space."""
    name: str
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class EventEngineConfig:
    """Thresholds for the deterministic event reasoning engine."""
    missing_timeout_s: float = 1.0
    loitering_threshold_s: float = 10.0
    running_speed_px_per_frame: float = 15.0
    # Unattended-object detection
    association_distance_px: float = 350.0
    separation_distance_px: float = 250.0
    unattended_threshold_s: float = 5.0
    zones: list[ZoneDefinition] = field(default_factory=lambda: [
        ZoneDefinition(name="entrance", x1=0, y1=0, x2=1000, y2=1000)
    ])


@dataclass
class VLMConfig:
    """VLM (Visual Language Model) runtime settings."""
    enabled: bool = False
    base_model_id: str = "microsoft/Florence-2-base-ft"
    # Path to LoRA adapter directory, relative to project root.
    # Set to None to run base model only.
    adapter_dir: str | None = "backend/vlm/models/sentinel-vqa-v1/best"
    # "cpu", "cuda", "auto"
    device: str = "auto"
    max_new_tokens: int = 4
    # Maximum pending event checks; new requests are explicitly skipped if full.
    queue_max_size: int = 8
    runtime_path: str | None = "data/evaluation/vlm_runtime"
    timeout_s: float = 60.0
    load_timeout_s: float = 180.0
    event_types: list[str] = field(default_factory=lambda: ["LOITERING", "UNATTENDED_OBJECT"])


@dataclass
class DatabaseConfig:
    """SQLite event database settings."""
    path: str = "data/sentinelai.db"


@dataclass
class EvidenceConfig:
    """Keyframe evidence capture settings."""
    output_dir: str = "data/events"
    # Only capture evidence for these event types. Empty = capture all.
    capture_event_types: list[str] = field(default_factory=list)


@dataclass
class APIConfig:
    """FastAPI / dashboard server settings."""
    host: str = "0.0.0.0"
    port: int = 8000
    # Number of recent events returned by default from /api/events
    default_event_limit: int = 50


@dataclass
class LLMConfig:
    """Direct local Hugging Face model; no inference server."""
    enabled: bool = False
    model_id: str = "HuggingFaceTB/SmolLM2-135M-Instruct"
    timeout_s: float = 45.0
    load_timeout_s: float = 180.0
    max_new_tokens: int = 96
    context_event_limit: int = 8
    cpu_threads: int = 2


@dataclass
class ESP32Config:
    """ESP32-CAM and actuation settings."""
    enabled: bool = False
    mode: str = "serial"
    serial_port: str | None = None
    baudrate: int = 115200
    stream_url: str = "http://192.168.1.100/stream"
    alert_url: str = "http://192.168.1.100/alert"


# ---------------------------------------------------------------------------
# Root settings dataclass
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    event_engine: EventEngineConfig = field(default_factory=EventEngineConfig)
    vlm: VLMConfig = field(default_factory=VLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    evidence: EvidenceConfig = field(default_factory=EvidenceConfig)
    api: APIConfig = field(default_factory=APIConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    esp32: ESP32Config = field(default_factory=ESP32Config)
    # Project root — resolved at load time.
    project_root: Path = field(default_factory=lambda: Path(__file__).parents[2])

    def resolve_path(self, relative: str) -> Path:
        """Return an absolute path relative to the project root."""
        p = Path(relative)
        if p.is_absolute():
            return p.resolve()
        return (self.project_root / relative).resolve()


# ---------------------------------------------------------------------------
# YAML loader (optional — only parses what's present)
# ---------------------------------------------------------------------------

def _apply_yaml(settings: Settings, yaml_path: Path) -> None:
    """
    Merge values from config.yaml into the default Settings object.
    Only keys that exist in the YAML override defaults; missing keys
    are left at their defaults.  No schema validation is enforced here —
    bad values will raise an error later when they are used.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — config.yaml will be ignored.")
        return

    with yaml_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    def _apply(obj: Any, data: dict) -> None:
        for key, value in data.items():
            if not hasattr(obj, key):
                logger.warning("Unknown config key: %s — ignored.", key)
                continue
            current = getattr(obj, key)
            if isinstance(current, list) and key == "zones" and isinstance(value, list):
                # Special handling for zone list
                setattr(obj, key, [
                    ZoneDefinition(**z) if isinstance(z, dict) else z
                    for z in value
                ])
            elif hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                _apply(current, value)
            else:
                setattr(obj, key, value)

    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping")
    _apply(settings, raw)
    logger.info("Loaded configuration from %s", yaml_path)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_settings: Settings | None = None


def get_settings(config_path: str | Path | None = None) -> Settings:
    """
    Return the global Settings singleton.

    On first call, searches for config.yaml in the project root.
    Subsequent calls return the cached singleton (ignoring config_path).

    Args:
        config_path: Override the YAML path for testing.

    Returns:
        Populated Settings instance.
    """
    global _settings
    if _settings is not None:
        return _settings

    settings = Settings()

    # Determine YAML path
    if config_path is None:
        candidate = Path(os.environ["SENTINEL_CONFIG"]) if os.environ.get("SENTINEL_CONFIG") else settings.project_root / "config.yaml"
    else:
        candidate = Path(config_path)

    if candidate.exists():
        _apply_yaml(settings, candidate)
    else:
        if config_path is not None or os.environ.get("SENTINEL_CONFIG"):
            raise FileNotFoundError(f"Configuration file not found: {candidate}")
        logger.info(
            "No config.yaml found at %s — using built-in defaults.",
            candidate,
        )

    if os.environ.get("SENTINEL_LLM_MODEL"):
        settings.llm.model_id = os.environ["SENTINEL_LLM_MODEL"]
    validate_settings(settings)
    _settings = settings
    return _settings


def validate_settings(cfg: Settings) -> None:
    if not 0 < cfg.detector.confidence_threshold <= 1:
        raise ValueError("detector.confidence_threshold must be in (0, 1]")
    if not 0 < cfg.detector.iou_threshold <= 1:
        raise ValueError("detector.iou_threshold must be in (0, 1]")
    if not 1 <= cfg.api.port <= 65535:
        raise ValueError("api.port must be in [1, 65535]")
    for value in (cfg.camera.width, cfg.camera.height, cfg.camera.fps,
                  cfg.camera.max_read_failures, cfg.vlm.queue_max_size,
                  cfg.event_engine.missing_timeout_s, cfg.event_engine.loitering_threshold_s,
                  cfg.event_engine.running_speed_px_per_frame,
                  cfg.event_engine.unattended_threshold_s):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError("Dimensions, rates, queue size and time thresholds must be positive")
    for value in (cfg.vlm.timeout_s, cfg.vlm.load_timeout_s, cfg.llm.timeout_s,
                  cfg.llm.load_timeout_s, cfg.llm.cpu_threads, cfg.llm.max_new_tokens,
                  cfg.llm.context_event_limit, cfg.vlm.max_new_tokens):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError("Model limits must be positive")
    for value in (cfg.llm.cpu_threads,cfg.llm.max_new_tokens,cfg.llm.context_event_limit,
                  cfg.vlm.max_new_tokens,cfg.vlm.queue_max_size):
        if type(value) is not int:
            raise ValueError("Model token, thread and queue limits must be integers")
    if cfg.vlm.max_new_tokens>16:
        raise ValueError("VLM answer token budget must not exceed 16")
    if cfg.llm.context_event_limit > 20 or cfg.llm.max_new_tokens > 256:
        raise ValueError("LLM context events <=20 and generation tokens <=256")
    for section in (cfg.vlm, cfg.llm, cfg.esp32):
        if not isinstance(section.enabled, bool):
            raise ValueError("enabled must be a YAML boolean")
    if cfg.esp32.mode not in {"serial", "stream"}:
        raise ValueError("esp32.mode must be serial or stream")
    if not isinstance(cfg.camera.source, (int, str)) or isinstance(cfg.camera.source, bool):
        raise ValueError("camera.source must be an index, path or URL")
    for zone in cfg.event_engine.zones:
        if zone.x2 <= zone.x1 or zone.y2 <= zone.y1:
            raise ValueError("Zone coordinates must have positive extent")


def reset_settings() -> None:
    """Reset the singleton — primarily for use in tests."""
    global _settings
    _settings = None
