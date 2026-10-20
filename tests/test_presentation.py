"""No heavyweight model or physical hardware in these regression tests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from scripts import presentation
from backend.api import routes


@pytest.fixture
def clocked_preview(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(routes.time,"monotonic",lambda:now[0])
    monkeypatch.setattr(routes,"_latest_jpeg",None)
    monkeypatch.setattr(routes,"_preview_info",(None,0))
    monkeypatch.setattr(routes,"_live_state",dict(camera_ok=True,model_loaded=True,pipeline_status="running",fps=30))
    monkeypatch.setattr(routes,"_db",SimpleNamespace(count_events=lambda:0))
    monkeypatch.setattr(routes,"_ai",None)
    monkeypatch.setattr(routes,"_llm",None)
    return now


def health():return json.loads(asyncio.run(routes.get_health()).body)


def test_frame_delivery_has_no_cache_and_progress_sequence(clocked_preview):
    routes.update_preview(b"first-frame")
    first=asyncio.run(routes.latest_frame())
    assert first.body==b"first-frame" and first.headers["cache-control"]=="no-store"
    routes.update_preview(b"second-frame")
    second=asyncio.run(routes.latest_frame())
    assert second.body==b"second-frame"
    assert first.headers["x-preview-sequence"]!=second.headers["x-preview-sequence"]
    assert health()["frames_arriving"] is True


def test_stale_frame_cannot_be_reported_live_or_served(clocked_preview):
    routes.update_preview(b"old-frame")
    clocked_preview[0]+=6
    result=health()
    assert result["preview_status"]=="stale" and not result["frames_arriving"]
    assert result["camera_status"]=="degraded" and result["status"]=="degraded" and result["fps"]==0
    with pytest.raises(HTTPException) as error:asyncio.run(routes.latest_frame())
    assert error.value.status_code==404


def test_disconnect_and_recovery_follow_actual_new_frame(clocked_preview):
    routes.update_preview(b"old")
    routes.update_live_state(camera_ok=False,pipeline_status="reconnecting")
    assert health()["camera_status"]=="reconnecting"
    with pytest.raises(HTTPException):asyncio.run(routes.latest_frame())
    clocked_preview[0]+=9
    routes.update_live_state(camera_ok=True,pipeline_status="running")
    assert not health()["frames_arriving"]
    routes.update_preview(b"recovered")
    assert health()["frames_arriving"]


def test_model_errors_are_degraded_and_error_is_visible(clocked_preview,monkeypatch):
    routes.update_preview(b"current")
    monkeypatch.setattr(routes,"_ai",SimpleNamespace(snapshot=lambda:dict(vlm=dict(enabled=True,state="error",error="missing weights"),llm=dict(enabled=True,state="loading"))))
    result=health()
    assert result["status"]=="degraded"
    assert result["models"]["vlm"]["error"]=="missing weights"
    assert not result["vlm_loaded"]


def test_source_error_is_not_healthy(clocked_preview):
    routes.update_live_state(camera_ok=False,pipeline_status="source_error",last_error="Camera unavailable")
    result=health()
    assert result["status"]=="error" and result["camera_status"]=="error"
    assert result["last_error"]=="Camera unavailable"


@pytest.fixture
def launcher_root(tmp_path,monkeypatch):
    import yaml
    from huggingface_hub import try_to_load_from_cache
    monkeypatch.setattr(presentation,"ROOT",tmp_path)
    config={"vlm":{"enabled":True,"runtime_path":None},"llm":{"enabled":True},"esp32":{"enabled":False},"api":{"host":"127.0.0.1","port":8010}}
    (tmp_path/"config.presentation.yaml").write_text(yaml.safe_dump(config))
    (tmp_path/"yolo11n.pt").write_bytes(b"fake weights never loaded")
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache",lambda *args:"fake cached config")
    return tmp_path,config


def test_normal_presentation_enables_models_without_opening_webcam(launcher_root,monkeypatch):
    import cv2
    monkeypatch.setattr(cv2,"VideoCapture",lambda *args:pytest.fail("Webcam opened in preflight"))
    info=presentation.prepare("0")
    assert "--vlm" in info["command"] and "--llm" in info["command"]
    assert "--no-vlm" not in info["command"] and "--no-llm" not in info["command"]
    assert info["serial_enabled"] is False and info["source_kind"]=="webcam"


def test_explicit_model_opt_out_is_supported(launcher_root):
    info=presentation.prepare("0",no_vlm=True,no_llm=True)
    assert "--no-vlm" in info["command"] and "--no-llm" in info["command"]
    assert "--vlm" not in info["command"]


def test_unsafe_serial_config_refused_before_camera_access(launcher_root):
    import yaml
    root,config=launcher_root;config["esp32"]["enabled"]=True
    (root/"config.presentation.yaml").write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError,match="disable ESP32"):presentation.prepare("0")


def test_missing_video_is_actionable(launcher_root):
    with pytest.raises(ValueError,match="not found"):presentation.prepare("missing.avi")


def test_undecodable_video_releases_capture(launcher_root,monkeypatch):
    import cv2
    root,_=launcher_root;(root/"broken.avi").write_bytes(b"not video")
    released=[]
    monkeypatch.setattr(cv2,"VideoCapture",lambda *args:SimpleNamespace(isOpened=lambda:False,release=lambda:released.append(True)))
    with pytest.raises(ValueError,match="decodable"):presentation.prepare("broken.avi")
    assert released==[True]


def test_missing_model_cache_reports_warning_without_faking_ready(launcher_root,monkeypatch):
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache",lambda *args:None)
    info=presentation.prepare("0")
    assert len(info["warnings"])==2
    assert "--vlm" in info["command"]


@pytest.mark.parametrize("check", [False, True])
def test_blocked_camera_is_actionable_without_starting_application(launcher_root, monkeypatch, capsys, check):
    import serial
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: pytest.fail("Physical serial opened"))
    monkeypatch.setattr(presentation.subprocess, "Popen", lambda *a, **k: pytest.fail("Application started"))
    args = ["--source", "esp32"] + (["--check"] if check else [])
    assert presentation.main(args) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert "ESP32 camera remains blocked" in output.out
    assert "no other video source was opened" in output.out
    assert "-Source 0" not in output.out and "data/demo/webcam.avi" not in output.out
    assert "no application log was created" in output.out
    assert not (launcher_root[0] / "data/logs").exists()


def test_other_preflight_failure_does_not_offer_camera_fallback(launcher_root, capsys):
    assert presentation.main(["--source", "missing.avi"]) == 2
    output = capsys.readouterr()
    assert "Video file not found" in output.out
    assert "-Source 0" not in output.out
    assert output.err == ""


def test_mjpeg_source_preflight_never_opens_network_or_serial(launcher_root,monkeypatch):
    import cv2
    monkeypatch.setattr(cv2,"VideoCapture",lambda *a:pytest.fail("Network opened in preflight"))
    info=presentation.prepare("http://192.0.2.1:81/stream")
    assert info["source_kind"]=="network_mjpeg" and not info["serial_enabled"]
    assert "--loop" not in info["command"] and "--vlm" in info["command"]



def test_explicit_esp32_never_substitutes_another_source(launcher_root,monkeypatch,capsys):
    import cv2,serial
    monkeypatch.setattr(cv2,"VideoCapture",lambda *a:pytest.fail("Fallback video opened"))
    monkeypatch.setattr(serial,"Serial",lambda *a,**k:pytest.fail("Physical serial opened"))
    monkeypatch.setattr(presentation.subprocess,"Popen",lambda *a,**k:pytest.fail("Backend started"))
    assert presentation.main(["--source", "esp32"])==2
    output=capsys.readouterr().out
    assert "ESP32 camera remains blocked" in output and "no other video source was opened" in output


@pytest.mark.parametrize("evidence,expected",[("software_fixture",False),("live_serial",True)])
def test_camera_status_requires_matching_receiver_provenance_and_fresh_preview(clocked_preview,evidence,expected):
    routes.update_preview(b"unit test preview, not sensor evidence")
    routes.update_live_state(source_kind="esp32_camera_uart",esp32_camera_verified=True,
        source_frame=dict(evidence_source=evidence),
        camera_transport=dict(evidence_source=evidence,decoded_frames=3,decoded_span_s=6,reconnects=0),
        frames_processed=3,tracker_status="ready")
    assert health()["esp32_camera_verified"] is expected
    clocked_preview[0]+=6
    assert health()["esp32_camera_verified"] is False


def test_camera_verified_status_flag_alone_never_proves_camera(clocked_preview):
    routes.update_preview(b"unit test")
    routes.update_live_state(source_kind="esp32_camera_uart",esp32_camera_verified=True)
    result=health()
    assert result["esp32_camera_verified"] is False
    assert result["camera_validation"]["jpeg_reception"]["state"]=="not_decoded"
    assert result["camera_validation"]["dashboard_preview"]["rendering"]=="requires_browser_validation"
