"""Bounded JSON-line diagnostics; no serial imports or hardware side effects."""
import json
import time

class LineFramer:
    def __init__(self, limit=1024):
        self.limit=limit;self.buffer=bytearray();self.dropping=False
        self.oversized=0
    def feed(self, data):
        lines=[]
        for byte in data:
            if byte==10:
                if not self.dropping and self.buffer:
                    lines.append(bytes(self.buffer).rstrip(b"\r"))
                self.buffer.clear();self.dropping=False
            elif not self.dropping:
                if len(self.buffer)<self.limit:self.buffer.append(byte)
                else:
                    self.buffer.clear();self.dropping=True;self.oversized+=1
        return lines

class Observation:
    def __init__(self, source="live_serial"):
        self.source=source;self.telemetry=None;self.camera=False
        self.invalid=0;self.boot_lines=0;self.unmatched=0;self.pending={}
        self.init="not_reported";self.capture="not_reported";self.sensor_pid=None
    def consume(self, raw):
        if raw.startswith((b"ets ",b"rst:",b"boot:")):
            self.boot_lines+=1;return None
        try:message=json.loads(raw)
        except (ValueError,UnicodeError):
            self.invalid+=1;return None
        if (not isinstance(message,dict) or type(message.get("protocol")) is not int
            or message["protocol"]!=1 or not isinstance(message.get("device_id"),str)
            or not 1<=len(message["device_id"])<=96
            or message.get("type") not in ("telemetry","ack","error","camera_ping_sent")):
            self.invalid+=1;return None
        identity=message["device_id"]
        if message["type"]=="telemetry":self.telemetry=message
        if message["type"]=="camera_ping_sent":
            nonce=message.get("sequence")
            if type(nonce) is int and 0<=nonce<=0xFFFFFFFF:
                if identity not in self.pending and len(self.pending)>=32:
                    del self.pending[next(iter(self.pending))]
                self.pending[identity]=nonce
            else:self.invalid+=1;return None
        if message["type"]=="ack" and message.get("command")=="camera_ping":
            if (identity in self.pending and type(message.get("sequence")) is int
                and message["sequence"]==self.pending[identity]
                and message.get("transport")=="uart2" and message.get("camera_reply")=="PONG"):
                self.camera=True
                del self.pending[identity]
                # Optional future fields are explicitly device reports, never a frame test.
                for field,attr in (("camera_init_status","init"),("capture_status","capture")):
                    value=message.get(field)
                    if value in ("ready","error","not_implemented"):
                        setattr(self,attr,"reported_"+value)
                pid=message.get("sensor_pid")
                if isinstance(pid,str) and len(pid)<=16:self.sensor_pid=pid
            else:self.unmatched+=1
        return message
    def report(self, oversized=0):
        state=("camera_responder_detected" if self.camera else
               "telemetry_detected" if self.telemetry else
               "wrong_protocol" if self.invalid or oversized else "timeout")
        return dict(state=state,evidence_source=self.source,
            telemetry_detected=self.telemetry is not None,
            camera_responder_detected=self.camera,
            device_id=self.telemetry.get("device_id") if self.telemetry else None,
            firmware=self.telemetry.get("firmware","SentinelTelemetry-compatible (unidentified)") if self.telemetry else None,
            camera_initialization=self.init,sensor_pid_reported=self.sensor_pid,
            capture_status=self.capture,frame_verified=False,
            new_physical_verification=False,
            invalid_lines=self.invalid,oversized_lines=oversized,
            unmatched_camera_replies=self.unmatched,
            diagnosis="A timeout or absent PONG does not establish that the camera is defective.")

class Reader:
    def __init__(self, port, observation, clock=time.monotonic):
        self.port=port;self.observation=observation;self.clock=clock
        self.framer=LineFramer();self.queue=[]
    def next(self):
        if not self.queue:
            self.queue.extend(self.framer.feed(self.port.read(256)))
        return self.observation.consume(self.queue.pop(0)) if self.queue else None
    def wait(self, predicate, timeout=5, identity=None):
        deadline=self.clock()+timeout
        while self.clock()<deadline:
            message=self.next()
            if not message:continue
            if identity is not None and message["device_id"]!=identity:continue
            if predicate(message):return message
            if message["type"]=="error":
                raise RuntimeError(message.get("error","Device error"))
        raise TimeoutError("No matching device response")

def send(port, value, clock=time.monotonic):
    data=memoryview((json.dumps(value,separators=(",",":"))+"\n").encode("ascii"))
    deadline=clock()+2
    while data:
        if clock()>=deadline:raise TimeoutError("Serial write deadline exceeded")
        count=port.write(data)
        if type(count) is not int or count<=0 or count>len(data):
            raise OSError("Serial write made no progress")
        data=data[count:]
    # No unbounded flush; pyserial writes have a configured write_timeout.

def diagnose(port, *, ping=False, seconds=5, power_verified=False,
             firmware_verified=False, clock=time.monotonic):
    if ping and not (power_verified and firmware_verified):
        raise ValueError("Active probe requires verified power and flashed firmware")
    obs=Observation();reader=Reader(port,obs,clock);phase="telemetry"
    result={};enabled_attempt=False;identity=None;cleanup=dict(state="not_required")
    try:
        if not ping:
            deadline=clock()+seconds
            while clock()<deadline:reader.next()
        else:
            telemetry=reader.wait(lambda m:m["type"]=="telemetry",seconds)
            identity=telemetry["device_id"]
            if telemetry.get("firmware")!="uart_probe":
                result.update(state="wrong_protocol",error="UART probe firmware is not running; telemetry firmware does not relay camera UART.")
            else:
                phase="enable";enabled_attempt=True
                send(port,dict(command="camera_uart_enable",power_verified=True),clock)
                reader.wait(lambda m:m["type"]=="ack" and m.get("command")=="camera_uart_enable",seconds,identity)
                phase="camera_ping"
                send(port,dict(command="camera_ping"),clock)
                sent=reader.wait(lambda m:m["type"]=="camera_ping_sent",seconds,identity)
                nonce=sent["sequence"]
                reply=reader.wait(lambda m:m["type"]=="ack" and m.get("command")=="camera_ping"
                    and type(m.get("sequence")) is int and m["sequence"]==nonce
                    and m.get("transport")=="uart2" and m.get("camera_reply")=="PONG",seconds,identity)
                result.update(state="camera_responder_detected",result="matched_uart_pong",
                              sequence=nonce,reply=reply,camera_identity_verified=False)
    except (TimeoutError,RuntimeError,OSError) as exc:
        result.update(state="timeout" if isinstance(exc,TimeoutError) or "timeout" in str(exc).lower() else "serial_error",
                      phase=phase,error=str(exc))
    finally:
        if enabled_attempt:
            try:
                send(port,dict(command="camera_uart_disable"),clock)
                reader.wait(lambda m:m["type"]=="ack" and m.get("command")=="camera_uart_disable",seconds,identity)
                cleanup=dict(state="confirmed_disabled")
            except (TimeoutError,RuntimeError,OSError) as exc:
                cleanup=dict(state="unconfirmed",error=str(exc))
                if result.get("state")=="camera_responder_detected":
                    result.update(state="cleanup_failed",error="PONG received, but UART2 shutdown was not confirmed")
    report=obs.report(reader.framer.oversized)
    if result.get("state")=="timeout" and phase=="telemetry" and report["state"]=="wrong_protocol":
        result["state"]="wrong_protocol"
    report.update(result)
    report["cleanup"]=cleanup
    return report

def inspect_log(data):
    obs=Observation("recorded_file");framer=LineFramer()
    for i in range(0,len(data),4096):
        for line in framer.feed(data[i:i+4096]):obs.consume(line)
    # JSONL permits an unterminated final record at EOF, but live streams don't.
    if framer.buffer and not framer.dropping:obs.consume(bytes(framer.buffer))
    result=obs.report(framer.oversized)
    result.update(serial_opened=False,hardware_operations_performed=False,
                  unterminated_record_at_eof=bool(framer.buffer))
    return result
