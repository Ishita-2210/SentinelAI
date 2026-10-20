"""Prepared camera source with an optional explicitly approved runtime relay.

Opening requires a separately verified transport. Tests inject fake byte streams.
"""
from datetime import datetime, timezone
import json
import queue
import threading
import time

import cv2
import numpy as np

from backend.camera.camera import CameraError
from backend.camera.uart_frames import JPEG, STATUS, Parser, jpeg_dimensions


class CameraSession:
    def __init__(self, camera_id, expected_nonce=None):
        self.camera_id = camera_id
        self.expected_nonce = expected_nonce
        self.responder_verified = False
        self.status = None
        self.session = None
        self.last_sequence = None
        self.last_capture_us = None
        self.gaps = self.replays = self.bad_status = self.restarts = 0
        self.last_error = None

    def consume(self, packet):
        if packet.kind == STATUS:
            try:
                value = json.loads(packet.payload)
                if (not isinstance(value, dict) or value.get("role") != "camera_capture"
                    or value.get("device_id") != self.camera_id):
                    raise ValueError("Unexpected camera identity/protocol")
                if self.session != packet.session:
                    if self.session is not None:self.restarts += 1
                    self.session = packet.session
                    self.responder_verified = False
                    self.last_sequence = self.last_capture_us = None
                self.status = value
                if self.expected_nonce is not None and type(value.get("pong_nonce")) is int and value["pong_nonce"] == self.expected_nonce:
                    self.responder_verified = True
                if value.get("init_status") != "ready" or value.get("capture_status") == "error":
                    self.last_error = str(value.get("error", "Camera initialization not ready"))[:256]
                else:self.last_error = None
            except (ValueError,UnicodeError,RecursionError) as exc:
                self.bad_status += 1
                self.last_error = str(exc)
                self.status = None
            return False
        if self.expected_nonce is not None and not self.responder_verified:
            self.last_error = "Awaiting matching camera PONG status"
            return False
        pid = self.status.get("sensor_pid") if self.status else None
        if (not self.status or self.status.get("init_status") != "ready"
            or self.status.get("capture_status") == "error"
            or type(pid) is not int or not 0 < pid <= 65535 or packet.session != self.session):
            self.last_error = "JPEG lacks matching initialized camera/PID status"
            return False
        if self.last_sequence is not None:
            delta = (packet.sequence-self.last_sequence) & 0xFFFFFFFF
            if delta == 0 or delta >= 0x80000000 or packet.capture_us < self.last_capture_us:
                self.replays += 1
                return False
            self.gaps += delta-1
        self.last_sequence, self.last_capture_us = packet.sequence, packet.capture_us
        return True


class Esp32CameraSource:
    is_file = False
    source_kind = "esp32_camera_uart"
    source_label = "ESP32 Camera"

    def __init__(self, approval, stream_factory=None, *, read_timeout_s=1,
                 stream_timeout_s=15, reconnect_s=.5, max_retries=3):
        self.approval = approval
        self.source = "esp32"
        self._factory = stream_factory or self._open_serial
        self._physical_stream = stream_factory is None
        self._read_timeout = read_timeout_s
        self._stream_timeout = stream_timeout_s
        self._reconnect_s = reconnect_s
        self._max_retries = max_retries
        self._queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = self._stream = None
        self._fatal = None
        self._state = "not_started"
        self.session = CameraSession(approval["camera_id"])
        self.frames_received = self.decoded_frames = self.dropped_frames = 0
        self.decode_errors = self.corrupt_frames = self.packet_timeouts = self.reconnects = 0
        self.last_error = None
        self.last_frame_at = self._first_frame = self._last_frame_clock = None
        self.frame_metadata = {}
        self.last_jpeg = None  # Exact last successfully decoded payload, bounded by MAX_PAYLOAD.
        self.frame_width = self.frame_height = 0
        self.port_opened = self.access_attempted = False
        self._generation = 0
        self._parser = None
        self._received_mono = None
        self._decode_failures = 0
        self._runtime = None
        self._first_decoded_clock = self._last_decoded_clock = None

    @property
    def evidence_source(self):
        return "live_serial" if self._physical_stream else "software_fixture"

    def _open_serial(self):
        import serial
        stream = serial.Serial(port=None, baudrate=self.approval["baud"], timeout=.1,
                               write_timeout=1, rtscts=False, dsrdtr=False)
        stream.dtr = False
        stream.rts = False
        stream.port = self.approval["port"]
        try:
            stream.open()
            self.port_opened = True
        except BaseException:
            stream.close()
            raise
        # Only an explicitly approved runtime role may issue bridge/PING controls.
        # Flashing, target reset and ROM-mode controls are never implemented here.
        return stream

    def open(self):
        if self._physical_stream:
            from backend.camera.hardware_gate import validate_approval
            try:validate_approval(self.approval)
            except ValueError as exc:raise CameraError(str(exc)) from exc
        if self._thread and self._thread.is_alive():raise CameraError("Camera source already open")
        self._stop.clear()
        self._fatal = None
        self._thread = threading.Thread(target=self._receive, name="esp32-receiver", daemon=True)
        try:self._thread.start()
        except RuntimeError as exc:raise CameraError("Receiver thread failed to start") from exc

    def _receive(self):
        failures = 0
        while not self._stop.is_set():
            parser = Parser(timeout_s=self._stream_timeout)
            self._parser = parser
            stream = None
            try:
                self._state = "connecting"
                self.access_attempted = True
                stream = self._factory()
                self.port_opened = True
                self._stream = stream
                self._generation += 1
                if self.approval.get("relay_control") == "programmer_runtime_v1":
                    from backend.camera.runtime_bridge import RuntimeBridge
                    self._runtime = RuntimeBridge(stream, approval=self.approval)
                    self._runtime.start()
                self.session = CameraSession(self.approval["camera_id"], self._runtime.nonce if self._runtime else None)
                self._clear_queue()
                connected_at = time.monotonic()
                last_valid = None
                while not self._stop.is_set():
                    if self._runtime:self._runtime.keepalive()
                    data = stream.read(4096)
                    for packet in parser.feed(data):
                        old_session = self.session.session
                        accepted = self.session.consume(packet)
                        if old_session != self.session.session or (packet.kind == STATUS and (not self.session.status or self.session.status.get("init_status") != "ready" or self.session.status.get("capture_status") == "error")):
                            self._clear_queue()
                        if not accepted:continue
                        try:jpeg_dimensions(packet.payload)
                        except ValueError as exc:
                            self.decode_errors += 1;self.last_error = str(exc);continue
                        now = time.monotonic()
                        last_valid = now
                        if self._first_frame is None:self._first_frame = now
                        self._last_frame_clock = now
                        received_at = datetime.now(timezone.utc).isoformat()
                        metadata = dict(source_kind=self.source_kind,source_label=self.source_label,
                            evidence_source=self.evidence_source,
                            device_id=self.approval["camera_id"],session=packet.session,
                            sequence=packet.sequence,capture_us=packet.capture_us,
                            received_at=received_at,connection_generation=self._generation,
                            sensor_pid_reported=self.session.status["sensor_pid"])
                        self.frames_received += 1
                        failures = 0
                        if self._queue.full():
                            self._clear_queue();self.dropped_frames += 1
                        self._queue.put_nowait((packet.payload,metadata,now))
                        self.last_error = None
                        self._state = "receiving"
                    # Joining midway through a maximum-size UART frame may
                    # require finishing that frame plus receiving the next one.
                    deadline_origin = last_valid if last_valid is not None else connected_at
                    allowance = self._stream_timeout if last_valid is not None else 2*self._stream_timeout
                    if time.monotonic()-deadline_origin > allowance:
                        raise TimeoutError("No validated camera frame within stream deadline")
            except (OSError,ValueError,RuntimeError) as exc:
                if not self._stop.is_set():
                    failures += 1;self.last_error = str(exc)
                    self._state = "reconnecting"
                    self._clear_queue()
                    if failures >= self._max_retries:
                        self._fatal = self.last_error;self._state = "error";break
                    self.reconnects += 1
            finally:
                self.corrupt_frames += parser.corrupt
                self.packet_timeouts += parser.timeouts
                self._parser = None
                if self._runtime:
                    try:self._runtime.stop()
                    except (RuntimeError,OSError) as exc:
                        self._fatal = "Relay shutdown unconfirmed: "+str(exc)
                        self.last_error = self._fatal
                        self._state = "error"
                        self._stop.set()  # Never rearm after unconfirmed shutdown.
                    self._runtime = None
                if stream is not None:
                    try:stream.close()
                    except OSError as exc:self.last_error = "Serial close failed: "+str(exc)
                self._stream = None
            self._stop.wait(self._reconnect_s)

    def _clear_queue(self):
        try:
            while True:self._queue.get_nowait()
        except queue.Empty:pass

    def read_frame(self):
        if self._fatal:raise CameraError(self._fatal)
        try:payload, metadata, arrived = self._queue.get(timeout=self._read_timeout)
        except queue.Empty:
            if self._fatal:raise CameraError(self._fatal)
            return False,None
        if time.monotonic()-arrived > self._stream_timeout:
            self.last_error = "Discarded stale buffered frame"
            return False,None
        try:frame = cv2.imdecode(np.frombuffer(payload,dtype=np.uint8),cv2.IMREAD_COLOR)
        except cv2.error:frame = None
        if frame is None:
            self.decode_errors += 1;self._decode_failures += 1
            self.last_error = "JPEG decode failed"
            if self._decode_failures >= 3:
                self._fatal = "Three consecutive JPEG decode failures"
                self._stop.set()
                raise CameraError(self._fatal)
            return False,None
        self._decode_failures = 0
        self.frame_height,self.frame_width = frame.shape[:2]
        self.frame_metadata = metadata
        self.last_jpeg = payload
        self.last_frame_at = metadata["received_at"]
        self._received_mono = arrived
        now = time.monotonic()
        if self._first_decoded_clock is None:self._first_decoded_clock = now
        self._last_decoded_clock = now
        self.decoded_frames += 1
        return True,frame

    def snapshot(self):
        elapsed = (self._last_frame_clock-self._first_frame) if self._first_frame is not None else 0
        decoded_span = self._last_decoded_clock-self._first_decoded_clock if self._first_decoded_clock is not None else 0
        return dict(state=self._state,frames_received=self.frames_received,
            evidence_source=self.evidence_source,serial_opened=self.port_opened,
            frame_age_s=max(0,time.monotonic()-self._received_mono) if self._received_mono is not None else None,
            decoded_span_s=decoded_span,observed_decoded_fps=(self.decoded_frames-1)/decoded_span if decoded_span>0 else 0,
            responder_challenged=self.session.expected_nonce is not None,
            camera_responder_verified=self.session.responder_verified,
            decoded_frames=self.decoded_frames,dropped_frames=self.dropped_frames,
            sequence_gaps=self.session.gaps,replayed_frames=self.session.replays,
            corrupt_packets=self.corrupt_frames+(self._parser.corrupt if self._parser else 0),
            packet_timeouts=self.packet_timeouts+(self._parser.timeouts if self._parser else 0),
            decode_errors=self.decode_errors,reconnects=self.reconnects,
            last_frame_at=self.last_frame_at,last_error=self.last_error or self.session.last_error,
            observed_transport_fps=(self.frames_received-1)/elapsed if elapsed>0 else 0,
            sensor_pid_reported=self.session.status.get("sensor_pid") if self.session.status else None,
            camera_initialization_reported=self.session.status.get("init_status") if self.session.status else None,
            frame_width=self.frame_width,frame_height=self.frame_height)

    @property
    def is_open(self):return bool(self._thread and self._thread.is_alive())

    def close(self):
        self._stop.set()
        stream = self._stream
        runtime = self._runtime
        if stream is not None and runtime is None:
            try:stream.close()
            except OSError as exc:self.last_error = str(exc)
        if self._thread:
            self._thread.join(timeout=40 if runtime else 2)
            if self._thread.is_alive():
                if stream is not None:stream.close()
                raise CameraError("Receiver shutdown not confirmed")
        if self._fatal and self._fatal.startswith("Relay shutdown unconfirmed"):
            raise CameraError(self._fatal)
        self._clear_queue()
        self._state = "closed"
