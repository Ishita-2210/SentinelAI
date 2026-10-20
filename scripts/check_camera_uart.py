"""Camera UART diagnostics. Default preparation mode never opens serial.
--input-file analyzes saved JSONL, not current hardware. Explicit hardware modes
require declarations; those declarations do not establish electrical safety.
"""
import argparse
import json
from pathlib import Path
import time
if __package__:
    from .camera_uart_diagnostics import diagnose, inspect_log
else:
    from camera_uart_diagnostics import diagnose, inspect_log

def read_message(port):
    """Compatibility helper; new diagnostics use bounded incremental framing."""
    raw=port.readline()
    if not raw or len(raw)>1024:return None
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):return None
    return value if isinstance(value,dict) and value.get("protocol")==1 and isinstance(value.get("device_id"),str) else None

def wait_for(port,predicate,timeout=5,clock=time.monotonic):
    deadline=clock()+timeout
    while clock()<deadline:
        message=read_message(port)
        if message and predicate(message):return message
        if message and message.get("type")=="error":raise RuntimeError(message.get("error","device error"))
    raise TimeoutError("No matching device response")

def probe(port, *, power_verified=False):
    if not power_verified:raise ValueError("Board-specific supply verification is required before UART enable")
    result=diagnose(port,ping=True,power_verified=True,firmware_verified=True)
    if result["state"]!="camera_responder_detected":
        error=result.get("error",result["state"])
        if result["state"]=="timeout":raise TimeoutError(error)
        raise RuntimeError(error)
    return result

def open_port(name):
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=1,rtscts=False,dsrdtr=False)
    port.dtr=False;port.rts=False;port.port=name
    try:port.open()
    except BaseException:port.close();raise
    return port

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    modes=ap.add_mutually_exclusive_group()
    modes.add_argument("--input-file",type=Path)
    modes.add_argument("--observe",action="store_true")
    modes.add_argument("--ping",action="store_true")
    ap.add_argument("--port",default="COM9")
    ap.add_argument("--seconds",type=float,default=5)
    ap.add_argument("--allow-serial-open",action="store_true")
    ap.add_argument("--power-verified",action="store_true")
    ap.add_argument("--firmware-verified",action="store_true")
    args=ap.parse_args(argv)
    if not 0<args.seconds<=60:ap.error("--seconds must be greater than zero and at most60")
    if args.input_file:
        try:
            if args.input_file.stat().st_size>8*1024*1024:raise ValueError("Log exceeds8MiB limit")
            result=inspect_log(args.input_file.read_bytes())
        except (OSError,ValueError) as exc:result=dict(state="file_error",error=str(exc),serial_opened=False)
    elif not (args.observe or args.ping):
        result=dict(state="preparation_only",serial_opened=False,hardware_operations_performed=False,
            camera_initialization="not_verified",capture_status="not_verified",
            frame_verified=False,required="Explicit serial-open permission and verified physical power; active probe also needs flashed probe firmware")
    elif not (args.allow_serial_open and args.power_verified and (not args.ping or args.firmware_verified)):
        result=dict(state="blocked",serial_opened=False,hardware_operations_performed=False,
            error="Requires --allow-serial-open --power-verified; --ping also requires --firmware-verified")
    else:
        port=None
        try:
            port=open_port(args.port)
            result=diagnose(port,ping=args.ping,seconds=args.seconds,
                power_verified=args.power_verified,firmware_verified=args.firmware_verified)
            result.update(serial_opened=True,hardware_operations_performed=True)
        except (OSError,ValueError,RuntimeError) as exc:
            result=dict(state="serial_error",error=str(exc),serial_opened=port is not None,
                        diagnosis="Connection failure is not a camera defect diagnosis")
        finally:
            if port is not None:
                try:port.close()
                except OSError as exc:
                    result.update(previous_state=result["state"],state="cleanup_failed",serial_close_error=str(exc))
    print(json.dumps(result,indent=2))
    return 0 if result["state"] in ("preparation_only","telemetry_detected","camera_responder_detected") else 1

if __name__=="__main__":raise SystemExit(main())
