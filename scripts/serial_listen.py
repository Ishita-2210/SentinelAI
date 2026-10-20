"""Manual passive UART capture; explicit --loopback sends only isolated-adapter probes.

No imports/startup in SentinelAI/preflight. No esptool, reset, flash or firmware changes.
ESP-A EN stays grounded. Default listen mode never calls write().
"""
import argparse
from datetime import datetime, timezone
import json
import secrets
import sys
import time


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ascii_view(data):
    return "".join(chr(b) if 32 <= b <= 126 else {9:r"\t",10:r"\n",13:r"\r"}.get(b,".") for b in data)


def open_port(port, baud, factory=None):
    import serial
    factory = factory or serial.Serial
    stream = factory(port=None, baudrate=baud, bytesize=serial.EIGHTBITS,
                     parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                     timeout=.1, write_timeout=1, xonxoff=False, rtscts=False, dsrdtr=False)
    # Set before opening; never toggle them during observation. Some OS/drivers
    # can still produce opening transients, which software cannot rule out.
    stream.dtr = False
    stream.rts = False
    stream.port = port
    try:stream.open()
    except BaseException:
        stream.close()
        raise
    return stream


def collect(stream, seconds=15, *, loopback=False, clock=time.monotonic,
            stamp=timestamp, emit=print, token=None):
    token = token or secrets.token_hex(4)
    started=clock();deadline=started+seconds;next_send=started
    total=printable=sent=echoes=0
    pending={};buffer=bytearray();interrupted=False
    try:
        while clock()<deadline:
            now=clock()
            if loopback and now>=next_send and deadline-now>=.5:
                payload=("SENTINEL_LOOP_"+token+"_"+str(sent+1)+"\r\n").encode("ascii")
                written=stream.write(payload)
                if written!=len(payload):raise OSError("Incomplete loopback probe write")
                sent+=1;pending[payload]=sent;next_send=now+1
                emit(stamp()+" TX probe="+str(sent)+" hex="+payload.hex(" "))
            data=stream.read(256)
            if not data:continue
            total+=len(data)
            printable+=sum(32<=b<=126 or b in (9,10,13) for b in data)
            emit(stamp()+" RX hex="+data.hex(" ")+" ASCII="+ascii_view(data))
            if loopback:
                buffer.extend(data)
                for payload,sequence in list(pending.items()):
                    if payload in buffer:
                        echoes+=1;del pending[payload]
                        emit(stamp()+" ECHO received probe="+str(sequence))
                # Enough for fragmented probes; never accumulate arbitrary logs.
                if len(buffer)>4096:del buffer[:-4096]
    except KeyboardInterrupt:
        interrupted=True
    summary=dict(mode="loopback" if loopback else "listen",received_bytes=total,
                 printable_bytes=printable,printable_ratio=printable/total if total else 0.0,
                 elapsed_s=round(clock()-started,3),interrupted=interrupted)
    if loopback:
        passed=sent>0 and echoes==sent
        summary.update(probes_sent=sent,probes_echoed=echoes,
                       result="PASS" if passed else "FAIL",
                       scope="isolated adapter echo only; CAM not tested")
    else:
        summary.update(result="DATA_RECEIVED" if total else "NO_DATA",
                       scope="received bytes only; printable ratio is not boot/origin proof",
                       transmitted_bytes=0)
    emit("SUMMARY "+json.dumps(summary,sort_keys=True))
    return summary


def enumerate_ports():
    from serial.tools import list_ports
    return list(list_ports.comports())  # Windows metadata only; no port opened.


def select_port(ports, requested=None):
    automatic = not requested or requested.upper() in ("AUTO", "COM_NUMBER")
    if not automatic:
        matches=[p for p in ports if p.device.casefold()==requested.casefold()]
        if len(matches)==1:return matches[0].device
        raise ValueError(requested+" is not present. Reconnect the laptop USB board, or omit --port for automatic USB selection.")
    usb=[p for p in ports if getattr(p,"vid",None) is not None and getattr(p,"pid",None) is not None]
    if len(usb)==1:return usb[0].device
    if not usb:
        raise ValueError("No USB serial adapter detected. Reconnect the laptop DevKit using the data cable that passed loopback. Check Device Manager for an unknown USB device. Bluetooth COM ports cannot reach CAM.")
    names=", ".join(p.device+" ("+(getattr(p,"description","") or "USB serial")+")" for p in usb)
    raise ValueError("Multiple USB serial adapters detected: "+names+". Specify --port with the laptop DevKit's actual port; none was opened.")


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",default="auto",help="Actual COM port, or auto (default): select a single USB serial adapter")
    parser.add_argument("--baud",type=int,default=115200)
    parser.add_argument("--seconds",type=float,default=15)
    parser.add_argument("--loopback",action="store_true")
    args=parser.parse_args(argv)
    if not 0<args.seconds<=3600:parser.error("--seconds must be >0 and <=3600")
    if not 300<=args.baud<=2000000:parser.error("Unsupported baud range")
    if args.loopback and args.seconds<1:parser.error("Loopback needs at least one second")
    try:
        ports=enumerate_ports()
        args.port=select_port(ports,args.port)
    except (ValueError,OSError) as exc:
        print("ERROR: "+str(exc),file=sys.stderr);return 2
    if args.baud==74880:print("NOTE: ESP32 ROM uses115200;74880 is an optional comparison, not its standard ROM baud.")
    print("Opening "+args.port+" "+str(args.baud)+" 8N1; DTR=False RTS=False; flow control off.",flush=True)
    print("LOOPBACK: CAM UART must be disconnected; sending probes." if args.loopback else "PASSIVE: no writes. After LISTENING appears, press/release CAM reset.",flush=True)
    stream=None
    try:
        stream=open_port(args.port,args.baud)
        print("LISTENING",flush=True)
        result=collect(stream,args.seconds,loopback=args.loopback,emit=lambda s:print(s,flush=True))
        return 1 if result["result"]=="FAIL" else 0
    except (OSError,ValueError) as exc:
        print("ERROR: "+str(exc),file=sys.stderr);return 2
    finally:
        if stream is not None:stream.close()


if __name__=="__main__":raise SystemExit(main())
