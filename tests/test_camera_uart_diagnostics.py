"""Software simulations only: no physical serial, GPIO or camera access."""
import json
import sys
from types import SimpleNamespace
import pytest
from scripts import camera_uart_diagnostics as d
from scripts import check_camera_uart as cli
from scripts import check_esp32


def msg(**fields):
    return json.dumps({"protocol":1,"device_id":"test",**fields}).encode()+b"\n"


class Clock:
    def __init__(self): self.t=0
    def __call__(self): self.t+=.01;return self.t


class Port:
    def __init__(self, *, pong=True, cleanup=True, firmware="uart_probe", failure=None):
        self.data=bytearray(msg(type="telemetry",firmware=firmware))
        self.writes=[];self.pong=pong;self.cleanup=cleanup;self.failure=failure
    def read(self,n):
        value=bytes(self.data[:n]);del self.data[:n];return value
    def write(self,value):
        command=json.loads(bytes(value));self.writes.append(command)
        name=command["command"]
        if name=="camera_uart_enable":self.data.extend(msg(type="ack",command=name))
        if name=="camera_ping":
            self.data.extend(msg(type="camera_ping_sent",sequence=123))
            if self.failure:self.data.extend(msg(type="error",error=self.failure))
            elif self.pong:self.data.extend(msg(type="ack",command=name,sequence=123,transport="uart2",camera_reply="PONG"))
        if name=="camera_uart_disable" and self.cleanup:self.data.extend(msg(type="ack",command=name))
        return len(value)


def run(port):
    return d.diagnose(port,ping=True,power_verified=True,firmware_verified=True,seconds=.3,clock=Clock())


def test_framer_fragmentation_crlf_and_bounded_overflow_recovery():
    framer=d.LineFramer(12)
    assert framer.feed(b"abc")==[]
    assert framer.feed(b"def\r\n")==[b"abcdef"]
    assert framer.feed(b"x"*100000)==[]
    assert len(framer.buffer)==0 and framer.oversized==1
    assert framer.feed(b"\nvalid\n")==[b"valid"]


@pytest.mark.parametrize("raw",[b"not json",b"[]",b'{"protocol":true,"device_id":"a","type":"telemetry"}',b'{"protocol":2,"device_id":"a","type":"telemetry"}',msg(type="other")])
def test_wrong_protocol_is_not_camera_failure(raw):
    report=d.inspect_log(raw+b"\n")
    assert report["state"]=="wrong_protocol"
    assert report["camera_responder_detected"] is False
    assert report["frame_verified"] is False


def test_historical_telemetry_does_not_establish_live_camera():
    result=d.inspect_log(msg(type="telemetry"))
    assert result["state"]=="telemetry_detected"
    assert result["evidence_source"]=="recorded_file"
    assert not result["new_physical_verification"] and not result["serial_opened"]
    assert result["camera_initialization"]=="not_reported"


@pytest.mark.parametrize("override",[dict(sequence=122),dict(sequence=True),dict(device_id="other"),dict(transport="usb"),dict(camera_reply="PING")])
def test_camera_requires_matching_identity_nonce_and_transport(override):
    observation=d.Observation()
    observation.consume(msg(type="camera_ping_sent",sequence=123))
    reply=dict(type="ack",command="camera_ping",sequence=123,transport="uart2",camera_reply="PONG")
    reply.update(override)
    observation.consume(msg(**reply))
    assert not observation.camera


def test_pong_optional_fields_are_reports_not_captured_frames_and_nonce_consumed():
    observation=d.Observation()
    observation.consume(msg(type="camera_ping_sent",sequence=123))
    reply=msg(type="ack",command="camera_ping",sequence=123,transport="uart2",camera_reply="PONG",camera_init_status="ready",capture_status="ready",sensor_pid="0x3660")
    observation.consume(reply)
    observation.consume(reply)
    result=observation.report()
    assert result["state"]=="camera_responder_detected"
    assert result["camera_initialization"]=="reported_ready"
    assert result["capture_status"]=="reported_ready" and result["frame_verified"] is False
    assert result["unmatched_camera_replies"]==1


def test_pending_nonce_memory_is_bounded():
    observation=d.Observation()
    for index in range(1000):observation.consume(msg(type="camera_ping_sent",sequence=index,device_id=str(index)))
    assert len(observation.pending)==32


def test_active_success_confirms_shutdown_and_keeps_init_unknown():
    port=Port();result=run(port)
    assert result["state"]=="camera_responder_detected"
    assert result["cleanup"]["state"]=="confirmed_disabled"
    assert result["camera_initialization"]=="not_reported"
    assert [x["command"] for x in port.writes]==["camera_uart_enable","camera_ping","camera_uart_disable"]


def test_timeout_is_inconclusive_and_cleanup_still_runs():
    result=run(Port(pong=False))
    assert result["state"]=="timeout" and "does not establish" in result["diagnosis"]
    assert result["cleanup"]["state"]=="confirmed_disabled"


def test_primary_failure_and_cleanup_failure_both_retained():
    result=run(Port(failure="camera_ping_timeout",cleanup=False))
    assert result["state"]=="timeout" and result["error"]=="camera_ping_timeout"
    assert result["cleanup"]["state"]=="unconfirmed"


def test_pong_with_unconfirmed_shutdown_is_not_clean_success():
    result=run(Port(cleanup=False))
    assert result["state"]=="cleanup_failed" and result["camera_responder_detected"]


def test_existing_telemetry_rejected_before_transmit():
    port=Port(firmware="SentinelTelemetry");result=run(port)
    assert result["state"]=="wrong_protocol" and result["telemetry_detected"]
    assert port.writes==[]


def test_active_requires_both_gates():
    port=Port()
    with pytest.raises(ValueError):d.diagnose(port,ping=True,power_verified=True)
    assert port.writes==[]


def test_passive_mode_never_transmits():
    port=Port();result=d.diagnose(port,seconds=.1,clock=Clock())
    assert result["state"]=="telemetry_detected" and not port.writes


def test_partial_writes_and_zero_progress():
    output=bytearray()
    def write(data):output.extend(data[:1]);return 1
    d.send(SimpleNamespace(write=write),dict(command="ping"),clock=Clock())
    assert bytes(output)==b'{"command":"ping"}\n'
    with pytest.raises(OSError,match="no progress"):
        d.send(SimpleNamespace(write=lambda data:0),dict(command="ping"))


def test_silent_and_wrong_protocol_streams_are_distinct():
    port=Port();port.data.clear()
    assert d.diagnose(port,seconds=.1,clock=Clock())["state"]=="timeout"
    port.data.extend(b"PING 123\n")
    assert d.diagnose(port,seconds=.1,clock=Clock())["state"]=="wrong_protocol"


def test_cli_default_file_and_missing_gates_never_open_port(monkeypatch,tmp_path,capsys):
    monkeypatch.setattr(cli,"open_port",lambda *args:pytest.fail("physical port opened"))
    assert cli.main([])==0
    assert json.loads(capsys.readouterr().out)["serial_opened"] is False
    for args in (["--observe"],["--ping","--power-verified"],["--ping","--allow-serial-open","--power-verified"]):
        assert cli.main(args)==1
        assert json.loads(capsys.readouterr().out)["state"]=="blocked"
    path=tmp_path/"saved.jsonl";path.write_bytes(msg(type="telemetry"))
    assert cli.main(["--input-file",str(path)])==0
    assert json.loads(capsys.readouterr().out)["evidence_source"]=="recorded_file"


def test_open_sets_control_lines_before_open_and_closes_on_failure(monkeypatch):
    events=[]
    class Device:
        def __setattr__(self,key,value):events.append((key,value));object.__setattr__(self,key,value)
        def open(self):events.append(("open",True));raise OSError("open failed")
        def close(self):events.append(("close",True))
    def factory(**kwargs):
        assert kwargs["port"] is None and kwargs["baudrate"]==115200
        return Device()
    monkeypatch.setitem(sys.modules,"serial",SimpleNamespace(Serial=factory))
    with pytest.raises(OSError):cli.open_port("FAKE")
    assert events==[("dtr",False),("rts",False),("port","FAKE"),("open",True),("close",True)]


def test_cli_closes_even_when_diagnosis_fails(monkeypatch,capsys):
    closed=[];port=SimpleNamespace(close=lambda:closed.append(True))
    monkeypatch.setattr(cli,"open_port",lambda name:port)
    def fail(*args,**kwargs):raise OSError("simulated disconnect")
    monkeypatch.setattr(cli,"diagnose",fail)
    assert cli.main(["--observe","--allow-serial-open","--power-verified"])==1
    assert json.loads(capsys.readouterr().out)["state"]=="serial_error"
    assert closed==[True]


def test_legacy_telemetry_checker_defaults_to_no_serial(capsys):
    assert check_esp32.main([])==0
    assert json.loads(capsys.readouterr().out)["serial_opened"] is False
    assert check_esp32.main(["--run"])==1
    assert json.loads(capsys.readouterr().out)["state"]=="blocked"


def test_serial_close_failure_is_reported(monkeypatch,capsys):
    def close():raise OSError("simulated close failure")
    monkeypatch.setattr(cli,"open_port",lambda name:SimpleNamespace(close=close))
    monkeypatch.setattr(cli,"diagnose",lambda *args,**kwargs:dict(state="telemetry_detected"))
    assert cli.main(["--observe","--allow-serial-open","--power-verified"])==1
    result=json.loads(capsys.readouterr().out)
    assert result["state"]=="cleanup_failed" and result["previous_state"]=="telemetry_detected"
    assert "close failure" in result["serial_close_error"]


def test_presentation_config_disables_serial_and_isolates_storage():
    from pathlib import Path
    import yaml
    config=yaml.safe_load(Path("config.presentation.yaml").read_text())
    assert config["esp32"]["enabled"] is False
    assert config["database"]["path"]=="data/presentation/sentinelai.db"
