"""Software-only transport tests; fake serial, no COM or ESP32 access."""
import json
from collections import deque
import socket
import pytest
from scripts import uart_programmer_bridge as bridge

def status(state="idle", **extra):
    return dict(bridge=1, firmware="sentinel_uart_programmer",state=state,
                baud=115200,rx_pin=16,tx_pin=17,host_idle_ms=30000,
                session_ms=900000, **extra)

class Clock:
    def __init__(self, step=.01): self.t=0;self.step=step
    def __call__(self): self.t+=self.step;return self.t

class Serial:
    def __init__(self, data=b"", max_write=4096):
        self.data=bytearray(data);self.written=bytearray();self.max_write=max_write
    def read(self,n):
        value=bytes(self.data[:n]);del self.data[:n];return value
    def write(self,data):
        value=bytes(data[:self.max_write]);self.written.extend(value);return len(value)

class Client:
    def __init__(self, chunks, max_send=4096):
        self.chunks=deque(chunks);self.sent=bytearray();self.max_send=max_send
    def recv(self,n):
        item=self.chunks.popleft() if self.chunks else b""
        if item is None:raise socket.timeout()
        return item
    def send(self,data):
        value=bytes(data[:self.max_send]);self.sent.extend(value);return len(value)

def test_arbitrary_binary_and_partial_writes_preserved_both_directions():
    upload=bytes(range(256))*4+b"\xc0\xdb\xdc\xdd\x00\r\nBRIDGE.STATUS\n"
    download=upload[::-1]
    serial=Serial(download,max_write=3);client=Client([upload,b""],max_send=5)
    result=bridge.relay(serial,client,clock=Clock(.0001))
    assert bytes(serial.written)==upload and bytes(client.sent)==download
    assert result["host_to_camera_bytes"]==len(upload)
    assert result["camera_to_host_bytes"]==len(download)

def test_fragmentation_and_no_text_interpretation():
    payload=b'BRIDGE.ARM POWER_VERIFIED BOOT_VERIFIED\n{"x":0}\x00\xc0\xdb'
    serial=Serial();client=Client([bytes([b]) for b in payload])
    bridge.relay(serial,client,clock=Clock(.0001))
    assert serial.written==payload

def test_idle_timeout():
    class Quiet(Client):
        def recv(self,n):raise socket.timeout()
    with pytest.raises(bridge.BridgeError,match="inactivity"):
        bridge.relay(Serial(),Quiet([]),idle_s=.1,clock=Clock(.02))

def test_session_timeout_even_with_continuous_traffic():
    class Busy(Client):
        def recv(self,n):return b"x"
    with pytest.raises(bridge.BridgeError,match="session timeout"):
        bridge.relay(Serial(),Busy([]),session_s=.2,clock=Clock(.01))

@pytest.mark.parametrize("flags",[(False,True,True),(True,False,True),(True,True,False)])
def test_arm_requires_every_physical_gate_before_write(flags):
    serial=Serial()
    with pytest.raises(bridge.BridgeError):
        bridge.arm_bridge(serial,power_verified=flags[0],
            boot_controls_verified=flags[1],target_download_mode=flags[2])
    assert not serial.written

def test_control_handshake_before_binary_and_wrong_state_rejected():
    serial=Serial(b"ROM boot noise\n"+json.dumps(status()).encode()+b"\n")
    assert bridge.inspect_bridge(serial)["state"]=="idle"
    assert serial.written==bridge.STATUS
    serial=Serial(json.dumps(status("raw")).encode()+b"\n")
    bridge.arm_bridge(serial,power_verified=True,boot_controls_verified=True,target_download_mode=True)
    assert serial.written==bridge.ARM
    with pytest.raises(bridge.BridgeError,match="Unexpected"):
        bridge.validate_status(status("locked"),"idle")

def test_shutdown_waits_without_tx_then_requires_locked_ack():
    serial=Serial()
    class ManualClock:
        t=0
        def __call__(self):return self.t
        def sleep(self,seconds):self.t+=.25
    clock=ManualClock()
    def write(value):
        assert clock.t>=32
        serial.data.extend(json.dumps(status("locked",reason="host_silent")).encode()+b"\n")
        serial.written.extend(value)
        return len(value)
    serial.write=write
    assert bridge.wait_locked(serial,clock=clock,sleep=clock.sleep)["state"]=="locked"
    assert serial.written==bridge.STATUS

def test_control_timeout_and_line_overflow():
    with pytest.raises(bridge.BridgeError,match="timeout"):
        bridge.read_status(Serial(),timeout=.1,clock=Clock(.02))
    with pytest.raises(bridge.BridgeError,match="too long"):
        bridge.read_status(Serial(b"x"*1026),clock=Clock(.00001))

def test_backpressure_and_zero_progress_fail():
    clock=Clock(.01)
    def blocked(data):raise socket.timeout()
    with pytest.raises(bridge.BridgeError,match="timeout"):
        bridge.write_all(blocked,b"abc",timeout=.1,clock=clock)
    with pytest.raises(bridge.BridgeError,match="no progress"):
        bridge.write_all(lambda data:0,b"abc")

def test_open_deasserts_controls_before_open_and_never_changes_baud():
    events=[]
    class Port:
        def __setattr__(self,key,value):
            events.append((key,value));object.__setattr__(self,key,value)
        def open(self):events.append(("open",self.port))
        def close(self):events.append(("close",True))
    def factory(**kwargs):
        assert kwargs["port"] is None and kwargs["baudrate"]==115200
        assert not kwargs["rtscts"] and not kwargs["dsrdtr"]
        return Port()
    bridge.open_devkit("FAKE",factory=factory)
    assert events==[("dtr",False),("rts",False),("port","FAKE"),("open","FAKE")]

def test_default_cli_and_missing_gate_never_open_serial(monkeypatch,capsys):
    monkeypatch.setattr(bridge,"open_devkit",lambda *args:pytest.fail("Serial was opened"))
    assert bridge.main([])==0
    assert json.loads(capsys.readouterr().out)["serial_opened"] is False
    assert bridge.main(["--serve"])==1


def test_single_local_client_is_accepted_before_uart_arm(monkeypatch):
    events=[]
    class Connected(Client):
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,value):events.append(("client_timeout",value))
    client=Connected([b"\x00\xff\xc0\xdb",b""])
    class Device(Serial):
        def write(self,data):
            value=bytes(data)
            if value==bridge.STATUS:self.data.extend(json.dumps(status()).encode()+b"\n")
            if value==bridge.ARM:
                assert ("accept",True) in events
                self.data.extend(json.dumps(status("raw")).encode()+b"\n"+b"\xc0\x00\xff")
            return super().write(data)
    device=Device()
    class Listener:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def bind(self,address):assert address==("127.0.0.1",3334)
        def listen(self,count):assert count==1
        def settimeout(self,value):assert value==60
        def getsockname(self):return ("127.0.0.1",3334)
        def accept(self):
            assert device.written==bridge.STATUS # no ARM before the local client
            events.append(("accept",True));return client,("127.0.0.1",1)
    monkeypatch.setattr(bridge.socket,"socket",lambda *args:Listener())
    monkeypatch.setattr(bridge,"wait_locked",lambda port:events.append(("shutdown",True)) or status("locked"))
    result=bridge.serve_once(device,power_verified=True,boot_controls_verified=True,target_download_mode=True)
    assert result["host_to_camera_bytes"]==4
    assert client.sent==b"\xc0\x00\xff"
    assert ("shutdown",True) in events

@pytest.mark.parametrize("cleanup_fails",[False,True])
def test_lost_arm_reply_still_runs_shutdown(monkeypatch,cleanup_fails):
    events=[]
    class ClientContext:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,value):pass
    class Listener:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def bind(self,address):pass
        def listen(self,count):pass
        def settimeout(self,value):pass
        def getsockname(self):return ("127.0.0.1",3334)
        def accept(self):return ClientContext(),("127.0.0.1",1)
    monkeypatch.setattr(bridge.socket,"socket",lambda *args:Listener())
    monkeypatch.setattr(bridge,"inspect_bridge",lambda port:status())
    def lost(*args,**kwargs):raise bridge.BridgeError("ARM response lost")
    monkeypatch.setattr(bridge,"arm_bridge",lost)
    def shutdown(port):
        events.append("shutdown")
        if cleanup_fails:raise bridge.BridgeError("locked response missing")
        return status("locked")
    monkeypatch.setattr(bridge,"wait_locked",shutdown)
    with pytest.raises(bridge.BridgeError,match="ARM response lost") as error:
        bridge.serve_once(Serial(),power_verified=True,boot_controls_verified=True,target_download_mode=True)
    assert events==["shutdown"]
    if cleanup_fails:assert "shutdown unconfirmed: locked response missing" in str(error.value)
