"""Bounded device check; does not flash or alter firmware."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.esp32.serial_device import parse_message
def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument("--port");ap.add_argument("--seconds",type=float,default=8)
    ap.add_argument("--run",action="store_true")
    ap.add_argument("--allow-serial-open",action="store_true")
    ap.add_argument("--power-verified",action="store_true")
    args=ap.parse_args(argv)
    if not args.run:
        print(json.dumps(dict(state="preparation_only",serial_opened=False)))
        return 0
    if not (args.allow_serial_open and args.power_verified):
        print(json.dumps(dict(state="blocked",serial_opened=False,
            error="Requires --allow-serial-open --power-verified before telemetry/alert transmissions")))
        return 1
    import serial
    from serial.tools import list_ports
    ports=list(list_ports.comports())
    print(json.dumps([dict(port=p.device,description=p.description,vid=p.vid,pid=p.pid) for p in ports]),flush=True)
    if not args.port:
        candidates=[p.device for p in ports if p.vid in {0x10C4,0x1A86,0x0403}]
        if len(candidates)!=1:
            print("UNAVAILABLE: no unique ESP32 USB-UART device");return 2
        args.port=candidates[0]
    messages=[];ack=False;telemetry=False;alert_ack=False
    with serial.Serial(args.port,115200,timeout=.5,write_timeout=.5) as stream:
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            raw=stream.readline(513)
            if not raw:continue
            try: msg=parse_message(raw)
            except ValueError:continue
            messages.append(msg);print(json.dumps(msg),flush=True)
            if msg["type"]=="telemetry":
                stream.write((json.dumps({"command":"alert","event_type":"LOITERING"},separators=(",",":"))+"\n").encode())
                telemetry=True;stream.write(b'{"command":"ping"}\n')
            if msg["type"]=="ack" and msg.get("command")=="ping":ack=True
            if msg["type"]=="ack" and msg.get("command")=="alert" and msg.get("event_type")=="LOITERING":alert_ack=True
            if telemetry and ack and alert_ack:break
    out=Path(__file__).resolve().parents[1]/"data/evaluation/esp32.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(port=args.port,telemetry=telemetry,ping_ack=ack,alert_ack=alert_ack,messages=messages),indent=2))
    return 0 if telemetry and ack and alert_ack else 1
if __name__=="__main__":sys.exit(main())
