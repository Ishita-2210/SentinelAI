"""USB serial JSON-lines contract for ESP32-WROOM-32; inference stays on host."""
import json
import queue
import threading
import time
EVENT_TYPES = {"PERSON_ENTERED", "PERSON_EXITED", "ZONE_CHANGED", "LOITERING", "RUNNING", "UNATTENDED_OBJECT"}

def parse_message(raw):
    if len(raw) > 512:
        raise ValueError("Serial message exceeds 512 bytes")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("protocol") != 1:
        raise ValueError("Unsupported ESP32 protocol")
    if value.get("type") not in {"telemetry", "ack", "error"}:
        raise ValueError("Unsupported ESP32 message type")
    if not isinstance(value.get("device_id"), str) or not value["device_id"]:
        raise ValueError("Missing device identity")
    if value["type"] == "telemetry":
        for key in ("uptime_ms", "free_heap"):
            if not isinstance(value.get(key), int) or isinstance(value[key], bool) or value[key] < 0:
                raise ValueError("Invalid telemetry: " + key)
    return value

class SerialDevice:
    def __init__(self, port=None, baudrate=115200, status_callback=None):
        self.port, self.baudrate = port, baudrate
        self.status = status_callback or (lambda **values: None)
        self._stop = threading.Event()
        self._commands = queue.Queue(maxsize=16)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._worker, name="esp32-serial", daemon=True)
        self._thread.start()

    def alert(self, event_type):
        if event_type not in EVENT_TYPES:
            raise ValueError("Unsupported alert")
        try:
            self._commands.put_nowait({"command": "alert", "event_type": event_type})
            return True
        except queue.Full:
            return False

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.status(esp32_status="stopped")

    def _worker(self):
        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            self.status(esp32_status="dependency_missing", esp32_error="Install pyserial")
            return
        while not self._stop.is_set():
            try:
                port = self.port
                if port is None:
                    candidates = [p.device for p in list_ports.comports()
                                  if p.vid in {0x10C4, 0x1A86, 0x0403}]
                    if len(candidates) != 1:
                        self.status(esp32_status="unavailable", esp32_error="Set esp32.serial_port; no unique USB-UART board")
                        self._stop.wait(2)
                        continue
                    port = candidates[0]
                self.status(esp32_status="connecting", esp32_port=port)
                with serial.Serial(port, self.baudrate, timeout=0.5, write_timeout=0.5) as stream:
                    last_valid = time.monotonic()
                    while not self._stop.is_set():
                        if time.monotonic() - last_valid > 5:
                            raise TimeoutError("No valid ESP32 telemetry for 5 seconds")
                        raw = stream.readline(513)
                        if raw:
                            try:
                                msg = parse_message(raw)
                            except (ValueError, UnicodeDecodeError) as exc:
                                self.status(esp32_status="invalid_payload", esp32_error=str(exc))
                                continue
                            if msg["type"] == "telemetry":
                                last_valid = time.monotonic()
                                self.status(esp32_status="connected", esp32_telemetry=msg, esp32_error=None)
                        if time.monotonic() - last_valid > 5:
                            raise TimeoutError("No valid ESP32 telemetry for 5 seconds")
                        try:
                            command = self._commands.get_nowait()
                        except queue.Empty:
                            continue
                        stream.write((json.dumps(command, separators=(",", ":")) + "\n").encode())
            except Exception as exc:
                self.status(esp32_status="disconnected", esp32_error=str(exc))
                self._stop.wait(2)
