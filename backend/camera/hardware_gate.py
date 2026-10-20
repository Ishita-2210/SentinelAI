"""Fail-closed, local operator evidence. This file never probes hardware."""
import json
from pathlib import Path
import re

REQUIRED = ("power_path_verified", "supply_budget_verified", "uart_routing_verified",
            "boot_reset_verified", "physical_ping_pong_verified", "camera_pinmap_verified", "capture_firmware_installed",
            "dedicated_transport_verified", "primary_telemetry_preserved",
            "port_open_reset_behavior_verified", "physical_origin_confirmed")
BLOCKER = ("ESP32 camera blocked: reported overheating during a 3V3 power experiment; keep the assembly unpowered pending electrical inspection. Capture is not installed/verified. Current route is ESP-A EN-low "
           "direct USB-UART with manual CAM IO0/reset, not the legacy GPIO16/17 relay. "
           "Serial/ROM tests are suspended by the current no-hardware instruction. "
           "ROM identification does not prove sensor initialization, camera mapping or JPEG capture.")


def approval_path(root):
    return Path(root)/"data/hardware_identification/camera_stream_approval.json"


def load_approval(root):
    path = approval_path(root)
    if not path.is_file():raise ValueError(BLOCKER)
    if path.stat().st_size > 8192:raise ValueError("Hardware approval record too large")
    try:record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:raise ValueError(BLOCKER) from exc
    return validate_approval(record)


def validate_approval(record):
    if not isinstance(record, dict) or record.get("schema") != 1 or any(record.get(k) is not True for k in REQUIRED):
        raise ValueError(BLOCKER)
    if not isinstance(record.get("port"), str) or not re.fullmatch(r"COM[1-9][0-9]*", record["port"], re.I):
        raise ValueError("Approval must identify a verified Windows stream port")
    if record.get("baud") != 115200 or type(record.get("baud")) is not int:
        raise ValueError("Only the115200-baud reference transport is prepared")
    if not isinstance(record.get("camera_id"), str) or not 1 <= len(record["camera_id"]) <= 96:
        raise ValueError("Approval must identify the physical camera device")
    mode = record.get("relay_control")
    if mode not in (None, "programmer_runtime_v1"):
        raise ValueError("Unsupported runtime relay role")
    if mode and record.get("camera_normal_boot_verified") is not True:
        raise ValueError("Runtime capture requires independently verified NORMAL camera boot, not ROM download mode")
    return record


def require_diagnostics(root, approval):
    import time
    path=Path(root)/"data/hardware_identification/camera_live_diagnostics.json"
    try:
        if path.stat().st_size > 32768:raise ValueError("Diagnostic record too large")
        record=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record,dict):raise ValueError("Diagnostic object required")
        age=time.time()-record["finished_at"]
        metrics=record.get("source_metrics") or {}
        frame=record.get("last_frame_metadata") or {}
        if not isinstance(metrics,dict) or not isinstance(frame,dict):raise ValueError("Diagnostic metrics/provenance required")
        pid=metrics.get("sensor_pid_reported")
        valid=(record.get("evidence_source")=="live_serial" and record.get("state")=="passed"
               and record.get("port")==approval["port"] and record.get("camera_id")==approval["camera_id"]
               and 0 <= age <= 86400 and record.get("valid_jpegs",0)>=3
               and record.get("observation_s",0)>=5
               and metrics.get("evidence_source")=="live_serial"
               and metrics.get("serial_opened") is True and metrics.get("decoded_frames",0)>=3
               and metrics.get("reconnects",0)==0 and type(pid) is int and 0<pid<=65535
               and frame.get("evidence_source")=="live_serial"
               and frame.get("device_id")==approval["camera_id"])
    except (OSError,ValueError,KeyError,TypeError):valid=False
    if not valid:raise ValueError("ESP32 camera blocked: fresh live diagnostics have not passed. Run scripts/check_esp32_camera.py after physical prerequisites are independently verified.")
    return record
