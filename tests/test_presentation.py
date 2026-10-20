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
