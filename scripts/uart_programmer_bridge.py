"""Prepare a future fixed-baud DevKit programming relay; default is inert.

No flash command is implemented. --serve requires three operator declarations.
Declarations do not measure power or establish target routing. Hardware mode is
blocked in the current project state; see docs/ESP32_SETUP.md.
"""
import argparse
import json
import socket
import sys
import time

BAUD = 115200
HOST_IDLE_S = 30
SESSION_S = 900
STATUS = b"BRIDGE.STATUS\n"
ARM = b"BRIDGE.ARM POWER_VERIFIED BOOT_VERIFIED\n"

class BridgeError(RuntimeError):
    pass

def require_hardware_gates(power_verified, boot_controls_verified, target_download_mode):
    if not all((power_verified, boot_controls_verified, target_download_mode)):
        raise BridgeError("Power, boot/reset controls and camera download mode must be independently verified")

def open_devkit(port_name, factory=None):
    if factory is None:
        import serial
        factory = serial.Serial
    # Construct closed: deassert lines BEFORE opening, not after.
    port = factory(port=None, baudrate=BAUD, timeout=.02, write_timeout=.5,
                   rtscts=False, dsrdtr=False)
    port.dtr = False
    port.rts = False
    port.port = port_name
    try:
        port.open()
    except BaseException:
        port.close()
        raise
    return port

def write_all(writer, data, *, timeout=1, clock=time.monotonic):
    deadline = clock() + timeout
    view = memoryview(data)
    while view:
        if clock() >= deadline:
            raise BridgeError("Write/backpressure timeout")
        try:
            count = writer(view)
        except (BlockingIOError, socket.timeout):
            continue
        if count is None or count <= 0 or count > len(view):
            raise BridgeError("Writer made no progress")
        view = view[count:]

def read_status(port, *, timeout=5, clock=time.monotonic):
    deadline = clock() + timeout
    line = bytearray()
    total = 0
    while clock() < deadline:
        value = port.read(1)
        if not value:
            continue
        total += len(value)
        if total > 65536:
            raise BridgeError("Excessive control noise")
        if value == b"\n":
            try:
                result = json.loads(line)
            except (ValueError, UnicodeError):
                result = None
            line.clear()
            if isinstance(result, dict) and result.get("bridge") == 1:
                if result.get("error"):
                    raise BridgeError(result["error"])
                return result
        elif len(line) < 1024:
            line.extend(value)
        else:
            raise BridgeError("Control line too long")
    raise BridgeError("Bridge control timeout")

def validate_status(info, expected_state):
    required = dict(firmware="sentinel_uart_programmer", state=expected_state,
                    baud=BAUD, rx_pin=16, tx_pin=17,
                    host_idle_ms=HOST_IDLE_S*1000, session_ms=SESSION_S*1000)
    if any(info.get(key) != value for key, value in required.items()):
        raise BridgeError("Unexpected bridge firmware/state/settings")
    return info

def inspect_bridge(port):
    write_all(port.write, STATUS)
    return validate_status(read_status(port), "idle")

def arm_bridge(port, *, power_verified=False, boot_controls_verified=False,
               target_download_mode=False):
    require_hardware_gates(power_verified, boot_controls_verified, target_download_mode)
    write_all(port.write, ARM)
    return validate_status(read_status(port), "raw")

def relay(port, client, *, idle_s=10, session_s=600, clock=time.monotonic):
    """One opaque TCP session. No baud, DTR/RTS, line or SLIP interpretation."""
    start = last_activity = clock()
    counts = dict(host_to_camera_bytes=0, camera_to_host_bytes=0)
    while True:
        now = clock()
        if now - start >= session_s:
            raise BridgeError("Relay session timeout")
        if now - last_activity >= idle_s:
            raise BridgeError("Relay inactivity timeout")
        try:
            data = client.recv(4096)
        except (BlockingIOError, socket.timeout):
            data = None
        if data == b"":
            return dict(reason="client_disconnected", **counts)
        if data:
            write_all(port.write, data, clock=clock)
            counts["host_to_camera_bytes"] += len(data)
            last_activity = clock()
        data = port.read(4096)
        if data:
            write_all(client.send, data, clock=clock)
            counts["camera_to_host_bytes"] += len(data)
            last_activity = clock()

def wait_locked(port, *, clock=time.monotonic, sleep=time.sleep):
    # No in-band escape is safe for arbitrary binary bytes. Stop host TX, drain
    # replies and let the independent MCU host-silence deadline disable UART2.
    deadline = clock() + HOST_IDLE_S + 2
    while clock() < deadline:
        port.read(4096)
        sleep(.01)
    write_all(port.write, STATUS, clock=clock)
    info = validate_status(read_status(port, clock=clock), "locked")
    return info

def serve_once(port, *, listen_port=3334, power_verified=False,
               boot_controls_verified=False, target_download_mode=False):
    require_hardware_gates(power_verified, boot_controls_verified, target_download_mode)
    # Only one local client; this is raw TCP, not RFC2217 or a network service.
    inspect_bridge(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", listen_port))
        listener.listen(1)
        listener.settimeout(60)
        print("One local client: socket://127.0.0.1:"+str(listener.getsockname()[1]), flush=True)
        client, _ = listener.accept()  # UART2 stays off until a client arrives.
        with client:
            client.settimeout(.02)
            arming_attempted = False
            primary_error = None
            try:
                arming_attempted = True
                arm_bridge(port, power_verified=power_verified,
                           boot_controls_verified=boot_controls_verified,
                           target_download_mode=target_download_mode)
                return relay(port, client)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                # ARM may have reached MCU even if the reply was lost.
                if arming_attempted:
                    print("Stopping host traffic; waiting for confirmed UART2 shutdown (about32s).",
                          file=sys.stderr, flush=True)
                    try:
                        info = wait_locked(port)
                    except (BridgeError, OSError) as cleanup_error:
                        detail = "UART2 shutdown unconfirmed: " + str(cleanup_error)
                        if primary_error is not None:
                            detail = str(primary_error) + "; " + detail
                        raise BridgeError(detail) from (primary_error or cleanup_error)
                    print(json.dumps(dict(bridge_shutdown=info)), file=sys.stderr, flush=True)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--listen-port", type=int, default=3334)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--power-verified", action="store_true")
    parser.add_argument("--boot-controls-verified", action="store_true")
    parser.add_argument("--target-download-mode", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be1..65535")
    if not args.serve:
        print(json.dumps(dict(mode="preparation_only", serial_opened=False,
            baud=BAUD, uart2_rx=16, uart2_tx=17, host_idle_s=HOST_IDLE_S,
            session_s=SESSION_S, bind="127.0.0.1",
            physical_requirements="verified camera power, routing, IO0/reset and download mode"), indent=2))
        return 0
    try:
        require_hardware_gates(args.power_verified, args.boot_controls_verified,
                               args.target_download_mode)
        port = open_devkit(args.port)
        try:
            result = serve_once(port, listen_port=args.listen_port,
                power_verified=args.power_verified,
                boot_controls_verified=args.boot_controls_verified,
                target_download_mode=args.target_download_mode)
            print(json.dumps(dict(transport_result=result, camera_identity_verified=False)))
        finally:
            port.close()
    except (BridgeError, OSError) as exc:
        print("Bridge failed: "+str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
