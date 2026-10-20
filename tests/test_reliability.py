"""Regression checks for real startup and temporal failure modes."""
import json
from datetime import timedelta
import pytest
from tests.test_event_engine import _make_track, _run_frame, T0
from backend.state_manager.state_manager import StateManager
from backend.event_engine.event_engine import EventEngine
from backend.esp32.serial_device import parse_message, SerialDevice

def test_temporary_track_loss_does_not_exit_or_duplicate_entry():
    sm, ee = StateManager(), EventEngine()
    track = _make_track(1,100,100,200,300)
    _run_frame(sm,ee,[track],T0)
    assert not _run_frame(sm,ee,[],T0+timedelta(seconds=.1))
    assert not _run_frame(sm,ee,[track],T0+timedelta(seconds=.2))
    events=_run_frame(sm,ee,[],T0+timedelta(seconds=1.3))
    assert [e.event_type for e in events]==["PERSON_EXITED"]
    assert not _run_frame(sm,ee,[],T0+timedelta(seconds=1.4))

def test_zone_reentry_resets_dwell():
    sm,ee=StateManager(),EventEngine()
    inside=_make_track(1,100,100,200,300)
    outside=_make_track(1,1100,100,1200,300)
    _run_frame(sm,ee,[inside],T0)
    _run_frame(sm,ee,[outside],T0+timedelta(seconds=2))
    ev=_run_frame(sm,ee,[inside],T0+timedelta(seconds=20))
    assert [x.event_type for x in ev]==["PERSON_ENTERED"]
    assert sm.states[1].zone_entered_at==T0+timedelta(seconds=20)

def test_owner_disappearing_near_object_can_be_unattended():
    sm,ee=StateManager(),EventEngine()
    ee.unattended_threshold=1
    person=_make_track(1,100,100,200,300)
    bag=_make_track(2,200,200,240,240,"backpack")
    _run_frame(sm,ee,[person,bag],T0)
    events=[]
    for i in range(1,30):
        events += _run_frame(sm,ee,[bag],T0+timedelta(seconds=i*.1))
    assert sum(e.event_type=="UNATTENDED_OBJECT" for e in events)==1

def test_velocity_is_consistent_across_frame_rates():
    values=[]
    for dt in (.1,.5):
        sm=StateManager()
        sm.update([_make_track(1,100,100,200,300)],T0)
        x=100+300*dt
        state=sm.update([_make_track(1,x,100,x+100,300)],T0+timedelta(seconds=dt))[0]
        values.append(state.velocity[0])
    assert values==pytest.approx([10,10])

def test_serial_valid_telemetry():
    raw=json.dumps(dict(protocol=1,type="telemetry",device_id="sentinel-test",uptime_ms=1000,free_heap=100000))
    assert parse_message(raw)["uptime_ms"]==1000

@pytest.mark.parametrize("raw",['bad','[]','{}','x'*513,
    '{"protocol":1,"type":"telemetry","device_id":"id","uptime_ms":-1,"free_heap":1}'])
def test_serial_rejects_malformed_payloads(raw):
    with pytest.raises(ValueError): parse_message(raw)

def test_serial_rejects_arbitrary_actuation():
    with pytest.raises(ValueError): SerialDevice().alert("SET_GPIO")

def test_standalone_api_initializes_own_database(tmp_path,monkeypatch):
    from backend.api import create_app, routes
    from backend.config.settings import Settings
    from fastapi.testclient import TestClient
    cfg=Settings(); cfg.database.path=str(tmp_path/"standalone.db")
    cfg.evidence.output_dir=str(tmp_path/"evidence")
    monkeypatch.setattr("backend.config.settings.get_settings",lambda:cfg)
    monkeypatch.setattr(routes,"_db",None)
    monkeypatch.setattr(routes,"_retriever",None)
    with TestClient(create_app()) as client:
        assert client.get("/api/events").json()=={"events":[],"count":0}
        assert client.get("/api/stats").json()["total"]==0
        assert client.get("/").status_code==200
    assert (tmp_path/"standalone.db").exists()
    assert routes._db is None

def test_configuration_rejects_invalid_threshold():
    from backend.config.settings import Settings, validate_settings
    cfg=Settings(); cfg.detector.confidence_threshold=2
    with pytest.raises(ValueError): validate_settings(cfg)

@pytest.mark.parametrize("raw", ["nobody", "yesterday", "not visible", "There is no person", "yes/no"])
def test_normalization_does_not_guess_from_substrings(raw):
    from backend.vlm_runtime.verifier import normalize_answer
    assert normalize_answer(raw)=="unknown"


def test_vlm_inference_preserves_token_dtype_and_casts_pixels():
    import torch
    from PIL import Image
    from backend.vlm_runtime.verifier import VisualVerifier
    class Processor:
        def __call__(self, **kwargs):
            return dict(input_ids=torch.tensor([[1,2]],dtype=torch.long),
                        attention_mask=torch.ones((1,2),dtype=torch.long),
                        pixel_values=torch.zeros((1,3,2,2),dtype=torch.float64))
        def batch_decode(self,*args,**kwargs):return ["yes"]
    class Model:
        def generate(self, **kwargs):
            assert kwargs["input_ids"].dtype==torch.long
            assert kwargs["pixel_values"].dtype==torch.float32
            assert "attention_mask" not in kwargs
            assert kwargs["do_sample"] is False
            return torch.tensor([[1]])
    verifier=VisualVerifier(enabled=False)
    verifier.enabled=True;verifier._torch=torch
    verifier._adapter_loaded=True  # Synthetic adapter output; base caption tested separately.
    verifier._device="cpu";verifier._dtype=torch.float32
    verifier._model=Model();verifier._processor=Processor()
    result=verifier.verify(Image.new("RGB",(2,2)),"Is a person visible?")
    assert result.answer=="yes"
    assert result.confidence is None

def test_camera_transient_failure_does_not_end_generator():
    from backend.camera.camera import CameraSource
    import numpy as np
    cam=CameraSource()
    cam._cap=object()
    frames=iter([(False,None),(True,np.zeros((2,2,3),dtype=np.uint8))])
    cam.read_frame=lambda:next(frames)
    assert next(cam.frames()).shape==(2,2,3)

def test_corrupt_looping_video_is_bounded():
    from backend.camera.camera import CameraSource,CameraError
    class Capture:
        def read(self):return False,None
        def set(self,*args):pass
    cam=CameraSource(source=0,loop_video=True)
    cam._is_file=True;cam._cap=Capture()
    with pytest.raises(CameraError):cam.read_frame()


def test_source_segment_reset_does_not_invent_loitering():
    sm,ee=StateManager(),EventEngine()
    track=_make_track(1,100,100,200,300)
    _run_frame(sm,ee,[track],T0)
    ee.reset();sm.states.clear()
    events=_run_frame(sm,ee,[track],T0+timedelta(seconds=100))
    assert [e.event_type for e in events]==["PERSON_ENTERED"]


def test_invalid_config_cannot_poison_settings_cache(tmp_path):
    from backend.config.settings import get_settings,reset_settings
    path=tmp_path/'invalid.yaml';path.write_text('detector:\n  confidence_threshold: 2\n')
    reset_settings()
    try:
        for _ in range(2):
            with pytest.raises(ValueError):get_settings(path)
    finally:reset_settings()


def test_serial_disconnect_is_reported_without_crashing(monkeypatch):
    import serial
    import threading
    from backend.esp32.serial_device import SerialDevice
    observed=[];ready=threading.Event()
    def fail(*args,**kwargs):raise serial.SerialException("simulated unplug")
    monkeypatch.setattr(serial,"Serial",fail)
    def status(**values):
        observed.append(values)
        if values.get("esp32_status")=="disconnected":ready.set()
    device=SerialDevice("COM-test",status_callback=status)
    device.start()
    try:assert ready.wait(2)
    finally:device.stop()
    assert any(x.get("esp32_error")=="simulated unplug" for x in observed)

def test_enabled_vlm_image_failure_stays_inconclusive():
    from backend.vlm_runtime.verifier import VisualVerifier
    verifier=VisualVerifier(enabled=False)
    verifier.enabled=True;verifier._model=object()
    result=verifier.verify("/missing/sentinel-image.jpg","Is a person visible?")
    assert result.answer=="unknown"
    assert result.confidence is None
    assert result.error.startswith("Image load error:")
