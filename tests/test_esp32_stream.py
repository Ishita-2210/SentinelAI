"""Software-only byte streams and generated test images; no hardware success."""
from collections import deque
from datetime import datetime,timezone
import json
import struct
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from backend.camera.uart_frames import Packet,Parser,encode,JPEG,STATUS,MAX_PAYLOAD,HEADER,jpeg_dimensions
from backend.camera.esp32_uart import CameraSession,Esp32CameraSource
from backend.camera.camera import CameraError
from backend.camera.hardware_gate import load_approval,require_diagnostics,REQUIRED
from scripts import check_esp32_camera as diagnostic
from scripts import presentation


def runtime_approval():
    return dict(schema=1,port="COM99",baud=115200,camera_id="test-camera",relay_control="programmer_runtime_v1",camera_normal_boot_verified=True,**{k:True for k in REQUIRED})


@pytest.fixture
def jpeg():
    ok,data=cv2.imencode(".jpg",np.full((48,64,3),100,dtype=np.uint8))
    assert ok
    return data.tobytes()


def status(session=1,**extra):
    value=dict(role="camera_capture",device_id="test-camera",init_status="ready",sensor_pid=0x1234)
    value.update(extra)
    return Packet(STATUS,session,0,0,json.dumps(value).encode())


def frame(jpeg,seq=1,session=1):return Packet(JPEG,session,seq,seq*100000,jpeg)


def test_every_byte_fragmented_and_noise_recovery(jpeg):
    parser=Parser();packets=[]
    payload=b"boot log\n"+encode(status())+encode(frame(jpeg))
    for byte in payload:packets.extend(parser.feed(bytes([byte])))
    assert [p.kind for p in packets]==[STATUS,JPEG]
    assert packets[-1].payload==jpeg and parser.noise_bytes==9


@pytest.mark.parametrize("offset",[4,5,6,8,16,24,28,33])
def test_corrupt_header_payload_or_crc_recovers_to_next_frame(jpeg,offset):
    damaged=bytearray(encode(frame(jpeg)))
    damaged[offset]^=0xFF
    parser=Parser(timeout_s=1,clock=lambda:0)
    packets=parser.feed(damaged+encode(frame(jpeg,2)))
    if not packets:
        # A corrupted plausible length can only be rejected after its deadline.
        parser.clock=lambda:2
        packets=parser.feed(b"")
    assert packets[-1].sequence==2 and parser.corrupt+parser.timeouts>0


def test_oversize_and_noise_buffer_memory_bounded():
    parser=Parser()
    assert not parser.feed(b"x"*1000000)
    assert len(parser.buffer)<=3
    bad=HEADER.pack(b"SNC1",1,JPEG,0,1,0,0,MAX_PAYLOAD+1,0)
    assert not parser.feed(bad) and parser.corrupt==1


def test_incomplete_payload_timeout_resynchronizes(jpeg):
    now=[0]
    parser=Parser(timeout_s=1,clock=lambda:now[0])
    assert not parser.feed(encode(frame(jpeg))[:50])
    now[0]=2
    result=parser.feed(encode(frame(jpeg,2)))
    assert result[-1].sequence==2 and parser.timeouts==1


@pytest.mark.parametrize("payload",[b"",b"bad",b"\xff\xd8\xff\xd9"])
def test_non_jpeg_cannot_be_decoded_as_camera_frame(payload):
    with pytest.raises(ValueError):jpeg_dimensions(payload)


def test_jpeg_dimension_budget_before_decode(jpeg):
    assert jpeg_dimensions(jpeg)==(64,48)
    with pytest.raises(ValueError,match="budget"):jpeg_dimensions(jpeg,max_pixels=10)


def test_requires_status_matching_boot_identity_and_real_pid(jpeg):
    session=CameraSession("test-camera")
    assert not session.consume(frame(jpeg))
    session.consume(status(device_id="other"))
    assert not session.consume(frame(jpeg))
    session.consume(status(sensor_pid=True))
    assert not session.consume(frame(jpeg))
    session.consume(status())
    assert not session.consume(frame(jpeg,session=2))
    assert session.consume(frame(jpeg))


def test_initialization_error_is_exposed_not_success(jpeg):
    session=CameraSession("test-camera")
    session.consume(status(init_status="error",error="sensor init failed"))
    assert session.last_error=="sensor init failed"
    assert not session.consume(frame(jpeg))


def test_sequence_gaps_duplicates_wraparound_and_restart(jpeg):
    session=CameraSession("test-camera");session.consume(status())
    assert session.consume(frame(jpeg,3))
    assert session.consume(frame(jpeg,6)) and session.gaps==2
    assert not session.consume(frame(jpeg,6))
    assert not session.consume(frame(jpeg,4))
    session.consume(status(session=2))
    assert session.consume(frame(jpeg,1,session=2)) and session.restarts==1
    session.last_sequence=0xFFFFFFFF;session.last_capture_us=0
    assert session.consume(frame(jpeg,0,session=2))


class Stream:
    def __init__(self,data):self.data=bytearray(data);self.closed=False;self.writes=[]
    def read(self,n):
        if self.closed:raise OSError("closed")
        if not self.data:time.sleep(.002);return b""
        value=bytes(self.data[:n]);del self.data[:n];return value
    def write(self,value):pytest.fail("Receive-only source transmitted to stream")
    def close(self):self.closed=True


def receiver(stream,**kwargs):
    return Esp32CameraSource(dict(camera_id="test-camera",port="COM99",baud=115200),lambda:stream,**kwargs)


def test_source_decodes_latest_frame_with_provenance_and_bounded_buffer(jpeg):
    stream=Stream(encode(status())+b"".join(encode(frame(jpeg,n)) for n in range(1,101)))
    camera=receiver(stream)
    camera.open()
    try:
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with camera._queue.mutex:
                ready=bool(camera._queue.queue and camera._queue.queue[-1][1]["sequence"]==100)
            if ready:break
            time.sleep(.002)
        ok,image=camera.read_frame()
        assert ok and image.shape==(48,64,3)
        assert camera.frame_metadata["sequence"]==100
        assert camera._queue.qsize()<=1 and camera.dropped_frames==99
        assert camera.frame_metadata["source_kind"]=="esp32_camera_uart"
        assert camera.snapshot()["decoded_frames"]==1
    finally:camera.close()
    assert stream.closed and not camera.is_open


def test_disconnect_reconnect_clears_stale_buffer_and_requires_new_status(jpeg):
    class Broken(Stream):
        def read(self,n):raise OSError("simulated unplug")
    first=Broken(b"");second=Stream(encode(status(2))+encode(frame(jpeg,session=2)))
    streams=deque([first,second])
    camera=Esp32CameraSource(dict(camera_id="test-camera"),lambda:streams.popleft(),reconnect_s=.001)
    camera.open()
    try:
        deadline=time.monotonic()+2
        while camera.frames_received<1 and time.monotonic()<deadline:time.sleep(.002)
        ok,image=camera.read_frame()
        assert ok and camera.frame_metadata["session"]==2
        assert camera.reconnects==1 and first.closed
    finally:camera.close()
    assert second.closed


def test_timeout_retries_are_bounded_and_cleanup_happens():
    streams=[]
    def connect():
        stream=Stream(b"");streams.append(stream);return stream
    camera=Esp32CameraSource(dict(camera_id="test-camera"),connect,stream_timeout_s=.01,reconnect_s=.001,max_retries=2,read_timeout_s=.01)
    camera.open()
    try:
        deadline=time.monotonic()+2
        while not camera._fatal and time.monotonic()<deadline:time.sleep(.002)
        with pytest.raises(CameraError,match="deadline"):camera.read_frame()
    finally:camera.close()
    assert len(streams)==2 and all(s.closed for s in streams)


def test_missing_approval_and_recorded_diagnostics_fail_closed(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match="ESP32 camera blocked"):load_approval(tmp_path)
    folder=tmp_path/"data/hardware_identification";folder.mkdir(parents=True)
    approval=dict(schema=1,port="COM99",baud=115200,camera_id="test-camera",**{k:True for k in REQUIRED})
    (folder/"camera_stream_approval.json").write_text(json.dumps(approval))
    assert load_approval(tmp_path)["port"]=="COM99"
    for evidence in ("recorded_file","simulation"):
        (folder/"camera_live_diagnostics.json").write_text(json.dumps(dict(state="passed",evidence_source=evidence,port="COM99",camera_id="test-camera",valid_jpegs=10,observation_s=10,finished_at=time.time())))
        with pytest.raises(ValueError,match="diagnostics"):require_diagnostics(tmp_path,approval)
    monkeypatch.setattr(presentation,"ROOT",tmp_path)
    # prepare validates hardware before choosing a stream or touching serial.
    from backend.config.settings import Settings
    import yaml
    (tmp_path/"config.presentation.yaml").write_text(yaml.safe_dump(dict(vlm=dict(enabled=True),llm=dict(enabled=True),esp32=dict(enabled=False),api=dict(host="127.0.0.1"))))
    with pytest.raises(ValueError,match="diagnostics"):presentation.prepare("esp32")


def test_default_and_missing_flags_diagnostic_never_import_receiver(monkeypatch,capsys):
    monkeypatch.setattr(diagnostic,"load_approval",lambda *args:pytest.fail("Gate should not be accessed"))
    assert diagnostic.main([])==2
    result=json.loads(capsys.readouterr().out)
    assert result["serial_opened"] is False and result["first_valid_jpeg"] is False
    assert result["observed_fps"] is None
    assert diagnostic.main(["--run"])==2


def test_event_source_metadata_is_persisted_and_retrieved(tmp_path):
    from backend.database.event_database import EventDatabase
    from backend.retrival.retrival import EventRetriever
    from backend.schemas.event import Event
    db=EventDatabase(str(tmp_path/"events.db"))
    try:
        metadata=dict(source_kind="simulated_transport_test",session=2,sequence=7,capture_us=123,received_at="2026-10-20T00:00:00+00:00")
        identity=db.save_event(Event("PERSON_ENTERED",1,"person",datetime.now(timezone.utc)),source_metadata=metadata)
        retriever=EventRetriever(db)
        assert retriever.get_by_id(identity)["source_metadata"]==metadata
        assert retriever.get_recent()[0]["source_metadata"]==metadata
        assert retriever.search("")[0]["source_metadata"]==metadata
    finally:db.close()


def test_esp32_mode_fails_before_model_start_without_approval(tmp_path,monkeypatch):
    from backend import main
    from backend.config.settings import Settings
    monkeypatch.setattr(main,"get_settings",lambda:Settings(project_root=tmp_path))
    assert main.run(SimpleNamespace(source="esp32"))==2


def test_receiver_frame_handoff_runs_existing_pipeline_and_preview(tmp_path,monkeypatch,jpeg):
    from backend import main
    from backend.config.settings import Settings
    from backend.camera import hardware_gate
    cfg=Settings(project_root=tmp_path)
    cfg.database.path="events.db";cfg.evidence.output_dir="events"
    cfg.vlm.enabled=cfg.llm.enabled=cfg.esp32.enabled=False
    monkeypatch.setattr(main,"get_settings",lambda:cfg)
    monkeypatch.setattr(hardware_gate,"load_approval",lambda root:dict(camera_id="test-camera"))
    monkeypatch.setattr(hardware_gate,"require_diagnostics",lambda *args:{})
    stream=Stream(encode(status())+encode(frame(jpeg)))
    camera=receiver(stream)
    monkeypatch.setattr("backend.camera.esp32_uart.Esp32CameraSource",lambda approval:camera)
    seen=[];previews=[]
    class Tracker:
        def __init__(self,**kwargs):pass
        def update(self,image):seen.append(image.copy());return []
        def reset(self):pass
    monkeypatch.setattr(main,"Tracker",Tracker)
    monkeypatch.setattr(main,"_start_api_server",lambda *args:None)
    from backend.api import routes
    monkeypatch.setattr(routes,"update_preview",lambda image:previews.append(image))
    # Avoid changing process signal handlers or leaving test live-state behind.
    monkeypatch.setattr(main.signal,"signal",lambda *args:None)
    monkeypatch.setattr(routes,"_live_state",dict(camera_ok=False,model_loaded=False))
    args=SimpleNamespace(source="esp32",vlm_enabled=False,llm_enabled=False,loop=False,max_frames=1,max_seconds=3,trace=None,no_display=True)
    assert main.run(args)==0
    assert len(seen)==1 and seen[0].shape==(48,64,3)
    assert previews and cv2.imdecode(np.frombuffer(previews[0],dtype=np.uint8),1).shape==(48,64,3)
    assert stream.closed


def test_repeated_decode_failure_is_bounded(jpeg,monkeypatch):
    camera=receiver(Stream(b""))
    monkeypatch.setattr(cv2,"imdecode",lambda *args:None)
    for attempt in range(3):
        camera._queue.put_nowait((jpeg,dict(received_at="test"),time.monotonic()))
        if attempt<2:assert camera.read_frame()==(False,None)
        else:
            with pytest.raises(CameraError,match="Three consecutive"):camera.read_frame()
    camera.close()


def test_diagnostic_retains_primary_and_cleanup_errors():
    def fail_read():raise CameraError("read failed")
    def fail_close():raise CameraError("close failed")
    source=SimpleNamespace(open=lambda:None,read_frame=fail_read,close=fail_close)
    with pytest.raises(RuntimeError,match="read failed; cleanup unconfirmed: close failed"):
        diagnostic.observe(source,10)


def test_runtime_challenge_requires_fresh_matching_pong_and_rechecks_boot(jpeg):
    session=CameraSession("test-camera",expected_nonce=42)
    session.consume(status(pong_nonce=41))
    assert not session.consume(frame(jpeg))
    session.consume(status(pong_nonce=True))
    assert not session.responder_verified
    session.consume(status(pong_nonce=42))
    assert session.responder_verified and session.consume(frame(jpeg))
    session.consume(status(session=2))
    assert not session.responder_verified and not session.consume(frame(jpeg,session=2))


def test_os_port_enumeration_is_not_serial_communication(monkeypatch,capsys):
    monkeypatch.setattr(diagnostic,"enumerate_ports",lambda:[dict(port="COM9",description="fake OS metadata",vid=0x1A86,pid=0x55D4)])
    assert diagnostic.main(["--list-ports"])==2
    report=json.loads(capsys.readouterr().out)
    assert report["stages"]["com_port"]["state"]=="enumerated"
    assert report["serial_opened"] is False
    assert report["stages"]["camera_responder"]["state"]=="not_tested"
    assert report["stages"]["first_jpeg"]["state"]=="not_received"


def test_runtime_bridge_arm_keepalive_and_shutdown_are_bounded_controls(monkeypatch):
    from backend.camera.runtime_bridge import RuntimeBridge
    from scripts import uart_programmer_bridge as bridge
    writes=[];events=[];now=[0]
    port=SimpleNamespace(write=lambda data:writes.append(bytes(data)) or len(data))
    monkeypatch.setattr(bridge,"inspect_bridge",lambda stream:events.append("inspect"))
    monkeypatch.setattr(bridge,"read_status",lambda stream:dict(state="raw"))
    monkeypatch.setattr(bridge,"validate_status",lambda value,state:events.append(state))
    monkeypatch.setattr(bridge,"wait_locked",lambda stream:events.append("confirmed_locked"))
    control=RuntimeBridge(port,clock=lambda:now[0],approval=runtime_approval())
    control.start()
    assert writes[0]==bridge.ARM and writes[1]==("PING "+str(control.nonce)+"\n").encode()
    control.keepalive();assert len(writes)==2
    now[0]=5;control.keepalive();assert len(writes)==3
    control.stop();assert events==["inspect","raw","confirmed_locked"]


def test_runtime_role_rejects_unverified_normal_boot(tmp_path):
    folder=tmp_path/"data/hardware_identification";folder.mkdir(parents=True)
    record=dict(schema=1,port="COM99",baud=115200,camera_id="test-camera",relay_control="programmer_runtime_v1",**{k:True for k in REQUIRED})
    (folder/"camera_stream_approval.json").write_text(json.dumps(record))
    with pytest.raises(ValueError,match="NORMAL"):load_approval(tmp_path)


def test_unconfirmed_runtime_shutdown_never_rearms(jpeg,monkeypatch):
    from backend.camera import runtime_bridge
    opened=[]
    class Control:
        nonce=42
        def __init__(self,port,**kwargs):pass
        def start(self):raise RuntimeError("arm reply lost")
        def stop(self):raise RuntimeError("shutdown missing")
    monkeypatch.setattr(runtime_bridge,"RuntimeBridge",Control)
    def factory():opened.append(True);return Stream(b"")
    camera=Esp32CameraSource(dict(camera_id="test-camera",relay_control="programmer_runtime_v1"),factory,reconnect_s=.001)
    camera.open()
    deadline=time.monotonic()+2
    while camera.is_open and time.monotonic()<deadline:time.sleep(.002)
    with pytest.raises(CameraError,match="shutdown unconfirmed"):camera.close()
    assert opened==[True]


def test_lost_runtime_arm_ack_still_requires_shutdown(monkeypatch):
    from backend.camera.runtime_bridge import RuntimeBridge
    from scripts import uart_programmer_bridge as bridge
    events=[]
    port=SimpleNamespace(write=lambda data:len(data))
    monkeypatch.setattr(bridge,"inspect_bridge",lambda stream:None)
    def lost(stream):raise bridge.BridgeError("lost ARM ack")
    monkeypatch.setattr(bridge,"read_status",lost)
    monkeypatch.setattr(bridge,"wait_locked",lambda stream:events.append("shutdown"))
    control=RuntimeBridge(port,approval=runtime_approval())
    with pytest.raises(bridge.BridgeError,match="lost ARM"):control.start()
    control.stop()
    assert events==["shutdown"]


def test_wrong_bridge_firmware_never_arms_or_waits_for_shutdown(monkeypatch):
    from backend.camera.runtime_bridge import RuntimeBridge
    from scripts import uart_programmer_bridge as bridge
    def wrong(stream):raise bridge.BridgeError("wrong firmware")
    monkeypatch.setattr(bridge,"inspect_bridge",wrong)
    monkeypatch.setattr(bridge,"wait_locked",lambda *args:pytest.fail("UART was never armed"))
    control=RuntimeBridge(SimpleNamespace(write=lambda data:pytest.fail("Unexpected ARM")),approval=runtime_approval())
    with pytest.raises(bridge.BridgeError,match="wrong firmware"):control.start()
    control.stop()


def test_midstream_join_gets_bounded_first_frame_grace(jpeg):
    class Joining(Stream):
        quiet=3
        def read(self,n):
            if self.quiet:
                self.quiet-=1;time.sleep(.04);return b""
            return super().read(n)
    stream=Joining(encode(status())+encode(frame(jpeg)))
    camera=receiver(stream,stream_timeout_s=.1,max_retries=1)
    camera.open()
    try:
        ok,image=camera.read_frame()
        assert ok and image.shape==(48,64,3) and camera.reconnects==0
    finally:camera.close()


def test_direct_physical_source_and_runtime_arming_require_full_approval():
    from backend.camera.runtime_bridge import RuntimeBridge
    camera=Esp32CameraSource(dict(camera_id="test-camera",port="COM9",baud=115200))
    with pytest.raises(CameraError,match="blocked"):camera.open()
    assert not camera.access_attempted
    control=RuntimeBridge(SimpleNamespace(write=lambda data:pytest.fail("Unsafe write")))
    with pytest.raises(RuntimeError,match="blocked"):control.start()



def test_first_frame_diagnostic_preserves_exact_received_jpeg(jpeg, tmp_path):
    import hashlib
    camera=receiver(Stream(encode(status())+encode(frame(jpeg))))
    path=tmp_path/"first.jpg"
    result=diagnostic.observe(camera,30,first_frame_only=True,save_first_jpeg=path)
    assert path.read_bytes()==jpeg
    assert result["first_jpeg_sha256"]==hashlib.sha256(jpeg).hexdigest()
    assert result["first_jpeg_metadata"]["device_id"]=="test-camera"
    assert result["first_valid_jpeg"] and result["valid_jpegs"]==1
    assert result["state"]=="first_frame_received" and not result["sustained_delivery"]
    assert not camera.is_open


def test_first_frame_export_never_overwrites_existing_file(jpeg,tmp_path):
    path=tmp_path/"first.jpg";path.write_bytes(b"existing evidence")
    camera=receiver(Stream(encode(status())+encode(frame(jpeg))))
    with pytest.raises(FileExistsError):
        diagnostic.observe(camera,30,first_frame_only=True,save_first_jpeg=path)
    assert path.read_bytes()==b"existing evidence" and not camera.is_open


def test_first_frame_options_never_bypass_physical_gate(tmp_path,monkeypatch,capsys):
    import serial
    monkeypatch.setattr(diagnostic,"ROOT",tmp_path)
    monkeypatch.setattr(serial,"Serial",lambda *a,**k:pytest.fail("Serial opened"))
    path=tmp_path/"first.jpg"
    assert diagnostic.main(["--first-frame","--save-first-jpeg",str(path)])==2
    result=json.loads(capsys.readouterr().out)
    assert not path.exists() and not result["serial_opened"]


def test_single_frame_result_cannot_authorize_continuous_launcher(tmp_path):
    folder=tmp_path/"data/hardware_identification";folder.mkdir(parents=True)
    approval=runtime_approval()
    record=dict(evidence_source="live_serial",state="first_frame_received",finished_at=time.time(),
        port=approval["port"],camera_id=approval["camera_id"],valid_jpegs=1,observation_s=0)
    (folder/"camera_live_diagnostics.json").write_text(json.dumps(record))
    with pytest.raises(ValueError,match="fresh live diagnostics"):require_diagnostics(tmp_path,approval)



def test_capture_error_status_withholds_jpeg_until_ready(jpeg):
    session=CameraSession("test-camera")
    session.consume(status(capture_status="error",error="capture failed"))
    assert not session.consume(frame(jpeg))
    session.consume(status(capture_status="ready"))
    assert session.consume(frame(jpeg))


@pytest.mark.parametrize("transport_state,expected_resets",[("receiving",1),("reconnecting",2)])
def test_pipeline_preserves_tracking_during_normal_slow_frame_wait(tmp_path,monkeypatch,transport_state,expected_resets):
    from backend import main
    from backend.config.settings import Settings
    from backend.camera import hardware_gate
    from backend.api import routes
    cfg=Settings(project_root=tmp_path)
    cfg.database.path="events.db";cfg.evidence.output_dir="events"
    cfg.vlm.enabled=cfg.llm.enabled=cfg.esp32.enabled=False
    monkeypatch.setattr(main,"get_settings",lambda:cfg)
    monkeypatch.setattr(hardware_gate,"load_approval",lambda root:dict(camera_id="simulated"))
    monkeypatch.setattr(hardware_gate,"require_diagnostics",lambda *args:{})
    class Camera:
        is_file=False
        count=0
        frame_metadata={}
        def open(self):pass
        def close(self):pass
        def snapshot(self):return dict(state=transport_state)
        def read_frame(self):
            self.count+=1
            if self.count==2:return False,None
            self.frame_metadata=dict(connection_generation=1,session=1,sequence=self.count,received_at=datetime.now(timezone.utc).isoformat())
            return True,np.zeros((48,64,3),dtype=np.uint8)
    camera=Camera();resets=[];seen=[]
    class Tracker:
        def __init__(self,**kwargs):pass
        def update(self,image):seen.append(True);return []
        def reset(self):resets.append(True)
    monkeypatch.setattr("backend.camera.esp32_uart.Esp32CameraSource",lambda approval:camera)
    monkeypatch.setattr(main,"Tracker",Tracker)
    monkeypatch.setattr(main,"_start_api_server",lambda *args:None)
    monkeypatch.setattr(main.signal,"signal",lambda *args:None)
    monkeypatch.setattr(routes,"_live_state",dict(camera_ok=False,model_loaded=False))
    monkeypatch.setattr(routes,"update_preview",lambda *args:None)
    args=SimpleNamespace(source="esp32",vlm_enabled=False,llm_enabled=False,loop=False,max_frames=2,max_seconds=3,trace=None,no_display=True)
    assert main.run(args)==0
    assert len(seen)==2 and len(resets)==expected_resets



def test_injected_stream_provenance_and_decode_age_are_explicit(jpeg):
    camera=receiver(Stream(encode(status())+encode(frame(jpeg))))
    camera.open()
    try:
        assert camera.read_frame()[0]
        assert camera.frame_metadata["evidence_source"]=="software_fixture"
        metrics=camera.snapshot()
        assert metrics["evidence_source"]=="software_fixture"
        assert metrics["frame_age_s"]>=0 and metrics["decoded_frames"]==1
        assert metrics["observed_decoded_fps"]==0
    finally:camera.close()


def test_declaring_passed_diagnostics_cannot_upgrade_fixture_origin(tmp_path):
    folder=tmp_path/"data/hardware_identification";folder.mkdir(parents=True)
    approval=runtime_approval()
    record=dict(state="passed",evidence_source="live_serial",port="COM99",camera_id="test-camera",valid_jpegs=10,observation_s=10,finished_at=time.time(),
        source_metrics=dict(evidence_source="software_fixture",serial_opened=True,decoded_frames=10,sensor_pid_reported=0x1234,reconnects=0),
        last_frame_metadata=dict(evidence_source="software_fixture",device_id="test-camera"))
    path=folder/"camera_live_diagnostics.json";path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match="diagnostics"):require_diagnostics(tmp_path,approval)
    # Pure schema acceptance test; this fabricated record is never physical evidence.
    record["source_metrics"]["evidence_source"]="live_serial"
    record["last_frame_metadata"]["evidence_source"]="live_serial"
    path.write_text(json.dumps(record))
    assert require_diagnostics(tmp_path,approval)["state"]=="passed"



@pytest.mark.parametrize("record",[[],42,dict(finished_at=0,source_metrics=["invalid"])])
def test_malformed_diagnostics_are_rejected_without_traceback(tmp_path,record):
    folder=tmp_path/"data/hardware_identification";folder.mkdir(parents=True)
    (folder/"camera_live_diagnostics.json").write_text(json.dumps(record))
    with pytest.raises(ValueError,match="diagnostics"):require_diagnostics(tmp_path,runtime_approval())



def test_camera_qa_filters_other_sources_before_latest_limit(tmp_path,monkeypatch):
    import asyncio
    from datetime import timedelta
    from backend.database.event_database import EventDatabase
    from backend.retrival.retrival import EventRetriever
    from backend.schemas.event import Event
    from backend.api import routes
    db=EventDatabase(str(tmp_path/"qa.db"));now=datetime.now(timezone.utc)
    try:
        def save(offset,**metadata):
            return db.save_event(Event("PERSON_ENTERED",1,"person",now+timedelta(seconds=offset)),source_metadata=metadata)
        actual=save(0,source_kind="esp32_camera_uart",evidence_source="live_serial",device_id="cam-a")
        save(1,source_kind="esp32_camera_uart",evidence_source="software_fixture",device_id="cam-a")
        save(2,source_kind="esp32_camera_uart",evidence_source="live_serial",device_id="cam-b")
        webcam=save(3,source_kind="webcam")
        monkeypatch.setattr(routes,"_retriever",EventRetriever(db))
        monkeypatch.setattr(routes,"_llm",None)
        monkeypatch.setattr(routes,"_live_state",dict(source_kind="esp32_camera_uart",source_frame=dict(device_id="cam-a")))
        response=asyncio.run(routes.llm_query(routes.LLMQueryRequest(question="When was the latest person entered event?")))
        assert json.loads(response.body)["source_event_ids"]==[actual]
        with pytest.raises(Exception) as exc:asyncio.run(routes.verify_event(webcam))
        assert exc.value.status_code==409
        routes._live_state["source_frame"]={}
        response=asyncio.run(routes.llm_query(routes.LLMQueryRequest(question="When was the latest person entered event?")))
        assert json.loads(response.body)["source_event_ids"]==[]
    finally:db.close()
