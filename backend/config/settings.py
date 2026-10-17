
"""Central configuration for SentinelAI."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load project-root .env without overriding existing environment values."""
    env_path = Path(__file__).resolve().parents[2] / ".env"

    if not env_path.is_file():
        return

    try:
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()

            if value.startswith(("'", '"')) and value.endswith(
                (value[0],)
            ):
                value = value[1:-1]

            if name and name not in os.environ:
                os.environ[name] = value
    except OSError:
        pass


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if value is None:
        return default.copy()
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    # Storage
    database_path: str = field(
        default_factory=lambda: _env("SENTINEL_DB", "data/sentinelai.db")
    )
    evidence_dir: str = field(
        default_factory=lambda: _env("SENTINEL_EVIDENCE_DIR", "data/events")
    )

    # Camera
    camera_source: str = field(
        default_factory=lambda: _env("SENTINEL_CAMERA", "0")
    )

    # Visual verification model
    vlm_enabled: bool = field(
        default_factory=lambda: _env_bool("SENTINEL_VLM_ENABLED", True)
    )
    vlm_model_id: str = field(
        default_factory=lambda: _env(
            "SENTINEL_VLM_MODEL", "microsoft/Florence-2-base-ft"
        )
    )
    vlm_adapter_path: str = field(
        default_factory=lambda: _env("SENTINEL_VLM_ADAPTER", "")
    )

    # Gemini API
    gemini_api_key: str = field(
        default_factory=lambda: _env("GEMINI_API_KEY", "")
    )
    gemini_api_keys: list[str] = field(
        default_factory=lambda: _env_list(
            "GEMINI_API_KEYS",
            [_env("GEMINI_API_KEY", "")] if _env("GEMINI_API_KEY", "") else [],
        )
    )
    gemini_model: str = field(
        default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash")
    )
    llm_timeout_sec: float = field(
        default_factory=lambda: float(_env("SENTINEL_LLM_TIMEOUT", "30"))
    )

    # Legacy Ollama settings retained for compatibility
    ollama_url: str = field(
        default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: _env("OLLAMA_MODEL", "llama3.2")
    )

    # Alerts / ESP32
    esp32_url: str = field(default_factory=lambda: _env("ESP32_URL", ""))
    alert_event_types: list[str] = field(
        default_factory=lambda: _env_list(
            "SENTINEL_ALERT_EVENTS",
            ["UNATTENDED_OBJECT", "LOITERING"],
        )
    )
    alert_cooldown_sec: float = field(
        default_factory=lambda: float(_env("SENTINEL_ALERT_COOLDOWN", "30"))
    )

    # API
    api_host: str = field(
        default_factory=lambda: _env("SENTINEL_HOST", "127.0.0.1")
    )
    api_port: int = field(
        default_factory=lambda: int(_env("SENTINEL_PORT", "8000"))
    )


def get_settings() -> Settings:
    """Build settings from the current environment."""
    return Settings()
