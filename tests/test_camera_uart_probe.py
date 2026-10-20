"""Host contract tests using simulated serial, never physical GPIO or firmware."""
import json
import pytest
from scripts.check_camera_uart import probe, wait_for

def msg(**fields):
    return json.dumps({"protocol": 1, "device_id": "sentinel-test", **fields}).encode()

class Port:
    def __init__(self, replies):
        self.replies = list(replies); self.writes = []
    def readline(self):
        if not self.replies:
            raise TimeoutError("simulated no reply")
        return self.replies.pop(0)
    def read(self, n):
        return self.readline()+b"\n"
    def write(self, value):
        command=json.loads(bytes(value));self.writes.append(command)
        if command["command"]=="camera_uart_disable":
            self.replies.append(msg(type="ack",command="camera_uart_disable"))
        return len(value)
    def flush(self): pass

def test_power_gate_never_writes():
    port = Port([])
    with pytest.raises(ValueError, match="supply verification"): probe(port)
    assert not port.writes

def replies():
    return [b"boot log\n", msg(type="telemetry", firmware="uart_probe"),
            msg(type="ack", command="camera_uart_enable"),
            msg(type="camera_ping_sent", sequence=123)]

def test_matching_reply_only_and_disables():
    port = Port(replies() + [
        msg(type="ack", command="ping"), # USB host ping is insufficient
        msg(type="ack", command="camera_ping", sequence=122, transport="uart2", camera_reply="PONG"),
        msg(type="ack", command="camera_ping", sequence=123, transport="uart2", camera_reply="PONG"),
    ])
    assert probe(port, power_verified=True)["result"] == "matched_uart_pong"
    assert port.writes[-1] == {"command": "camera_uart_disable"}

def test_camera_timeout_is_not_success_and_disables():
    port = Port(replies() + [msg(type="error", error="camera_ping_timeout")])
    with pytest.raises(TimeoutError, match="camera_ping_timeout"):
        probe(port, power_verified=True)
    assert port.writes[-1]["command"] == "camera_uart_disable"

def test_old_telemetry_firmware_rejected_without_uart_enable():
    port = Port([msg(type="telemetry")])
    with pytest.raises(RuntimeError, match="not running"): probe(port, power_verified=True)
    assert not port.writes

def test_wait_deadline_is_bounded():
    ticks = iter([0, 0, 2])
    port = Port([b"not json"])
    with pytest.raises(TimeoutError):
        wait_for(port, lambda m: True, timeout=1, clock=lambda: next(ticks))
