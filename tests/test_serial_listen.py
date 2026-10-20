"""Fake streams/clocks only; no serial device is opened."""
import json
import pytest
from scripts import serial_listen as listen


class Stream:
    def __init__(self,echo=False,data=b""):
        self.now=0.;self.echo=echo;self.data=bytearray(data);self.writes=[]
    def read(self,n):
        self.now+=.1
        # Fragment every echo across reads.
        result=bytes(self.data[:3]);del self.data[:3];return result
    def write(self,data):
        self.writes.append(data)
        if self.echo:self.data.extend(data)
        return len(data)


def test_passive_never_writes_and_counts_ascii_with_timestamps():
    stream=Stream(data=b"ets\r\n\x00\xff")
    stream.write=lambda data:pytest.fail("Passive write")
    output=[]
    result=listen.collect(stream,1,clock=lambda:stream.now,stamp=lambda:"STAMP",emit=output.append)
    assert result["received_bytes"]==7 and result["printable_bytes"]==5
    assert result["printable_ratio"]==5/7 and result["transmitted_bytes"]==0
    assert any(line.startswith("STAMP RX hex=") and "ASCII=" in line for line in output)


@pytest.mark.parametrize("echo",[False,True])
def test_loopback_requires_actual_fragmented_rx_echo(echo):
    stream=Stream(echo=echo)
    result=listen.collect(stream,3,loopback=True,clock=lambda:stream.now,emit=lambda s:None,token="TEST")
    assert result["probes_sent"]==3 and len(stream.writes)==3
    assert result["probes_echoed"]==(3 if echo else 0)
    assert result["result"]==("PASS" if echo else "FAIL")


def test_open_configures_false_lines_before_open_and_disables_flow_control():
    events=[];kwargs_seen={}
    class Port:
        def __setattr__(self,key,value):events.append((key,value));object.__setattr__(self,key,value)
        def open(self):events.append(("open",True))
        def close(self):events.append(("close",True))
    def factory(**kwargs):kwargs_seen.update(kwargs);return Port()
    listen.open_port("FAKE",115200,factory)
    assert events==[("dtr",False),("rts",False),("port","FAKE"),("open",True)]
    assert kwargs_seen["port"] is None and kwargs_seen["bytesize"]==8
    assert kwargs_seen["parity"]=="N" and kwargs_seen["stopbits"]==1
    assert not any(kwargs_seen[k] for k in ("xonxoff","rtscts","dsrdtr"))


def test_main_always_closes_on_receive_failure(monkeypatch):
    closed=[]
    stream=type("Port",(),{"close":lambda self:closed.append(True)})()
    monkeypatch.setattr(listen,"enumerate_ports",lambda:[type("Info",(),{"device":"FAKE"})()])
    monkeypatch.setattr(listen,"open_port",lambda *a:stream)
    def fail(*a,**k):raise OSError("fake disconnect")
    monkeypatch.setattr(listen,"collect",fail)
    assert listen.main(["--port","FAKE"])==2 and closed==[True]


def test_no_data_summary_does_not_claim_camera_failure():
    stream=Stream()
    result=listen.collect(stream,.5,clock=lambda:stream.now,emit=lambda s:None)
    assert result["received_bytes"]==0 and result["printable_ratio"]==0
    assert result["result"]=="NO_DATA" and not stream.writes


def test_auto_and_placeholder_select_only_usb_adapter():
    from types import SimpleNamespace
    bluetooth=SimpleNamespace(device="COM3",vid=None,pid=None)
    adapter=SimpleNamespace(device="COM10",vid=0x1A86,pid=0x55D4,description="CH9102")
    for requested in (None,"auto","COM_NUMBER"):
        assert listen.select_port([bluetooth,adapter],requested)=="COM10"


def test_missing_usb_never_opens_bluetooth_or_placeholder(monkeypatch,capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(listen,"enumerate_ports",lambda:[SimpleNamespace(device="COM3",vid=None,pid=None)])
    monkeypatch.setattr(listen,"open_port",lambda *a:pytest.fail("Port opened"))
    assert listen.main(["--port","COM_NUMBER"])==2
    assert "No USB serial adapter detected" in capsys.readouterr().err


def test_multiple_adapters_and_absent_explicit_port_are_not_guessed():
    from types import SimpleNamespace
    adapters=[SimpleNamespace(device=name,vid=1,pid=2,description="USB") for name in ("COM9","COM10")]
    with pytest.raises(ValueError,match="Multiple"):listen.select_port(adapters)
    with pytest.raises(ValueError,match="not present"):listen.select_port(adapters,"COM11")
    assert listen.select_port(adapters,"com10")=="COM10"
