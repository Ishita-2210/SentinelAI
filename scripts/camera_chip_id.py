"""Manual ROM ID only; never run by preflight.
Reported baseline: ESP-A EN->GND, GPIO3/RX0->CAM U0R,
GPIO1/TX0<-CAM U0T, ESP-A GND->ESP-B GND->CAM GND.
ESP-B5V->CAM5V; CAM IO0->GND at manual reset. No ESP-A flashing.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def select_port(ports, requested=None):
    if requested:
        matches = [p for p in ports if p.device.casefold() == requested.casefold()]
    else:
        matches = [p for p in ports if p.vid == 0x1A86 and p.pid == 0x55D4]
    if len(matches) != 1:
        raise ValueError("Identify ESP-A in Device Manager, then specify -Port COMn; no unique matching port")
    return matches[0].device


def no_data_checklist(emit):
    emit("No serial data received: check these in order; no retry or wiring change is automatic.")
    emit("1. CAM IO0 may not actually be grounded at reset. Keep IO0-GND connected and press/release CAM reset (not ESP-A reset).")
    emit("2. Check CAM U0R/U0T labels and loose jumpers: ESP-A GPIO3/RX0 -> CAM U0R; GPIO1/TX0 <- CAM U0T. Check the common ground through ESP-B.")
    emit("3. Weak/unstable CAM5V: check CAM input/3V3 under load. Optional source comparison ONLY if ESP-A's USB-to-5V path/current capacity is established: power everything off, REMOVE ESP-B5V->CAM5V, then use ESP-A5V as CAM's ONLY positive supply with common GND. NEVER connect both 5V outputs. ESP-A5V capacity is not established by this test/log; do not assume it.")
    emit("4. ESP-A EN must remain grounded; otherwise its ESP32 can drive the shared UART and fight the adapter. Its firmware need not be changed.")
    emit("5. Confirm ESP-A's COM port in Device Manager and close other users/serial monitors. Enumeration alone does not prove a working adapter path.")
    emit("Optional ESP-A-only loopback, performed manually: with sources off disconnect BOTH CAM UART wires, keep ESP-A EN-GND, jumper ESP-A RX0/GPIO3 to TX0/GPIO1; power ESP-A USB only. Open a terminal at1152008N1 with flow control OFF and LOCAL ECHO OFF; transmitted characters must return as received characters. Close terminal before esptool. Power off before removing loopback and restoring CAM wiring. A pass proves this adapter TX/RX path, not CAM power/boot/sensor. This script does not open a terminal or perform loopback.")


def identify(port, runner=subprocess.run, emit=print):
    base = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port,
            "--baud", "115200", "--before", "no-reset", "--after", "no-reset",
            "--no-stub", "--connect-attempts", "2"]
    for operation in ("chip-id", "flash-id"):
        emit("Running: " + subprocess.list2cmdline(base + [operation]))
        try:
            result = runner(base + [operation], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            for output in (getattr(exc, "stdout", None), getattr(exc, "stderr", None)):
                if output:emit(output.decode("utf-8", "replace") if isinstance(output, bytes) else output)
            emit("FAIL: " + operation + ": " + str(exc))
            return 1
        emit(result.stdout or "")
        emit(result.stderr or "")
        if result.returncode:
            if "no serial data received" in ((result.stdout or "") + (result.stderr or "")).casefold():
                no_data_checklist(emit)
            emit("FAIL: " + operation + "; no further hardware command attempted")
            return 1
    emit("PASS: ESP32 ROM identification and SPI flash ID completed; sensor/JPEG NOT tested.")
    emit("CAM origin depends on ESP-A EN actually being held low. Compare reported MAC with known ESP-A MAC.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    args = parser.parse_args(argv)
    from serial.tools import list_ports
    ports = list(list_ports.comports())  # OS metadata; does not open ports.
    for p in ports:print(p.device + "  " + (p.description or ""))
    try:port = select_port(ports, args.port)
    except ValueError as exc:
        print("FAIL: " + str(exc));return 1
    print("Selected ESP-A port: " + port)
    print("Manual download mode required. No automatic reset, RAM stub, firmware upload or erase.")
    log_dir = ROOT / "data/hardware_identification"
    log_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    path = log_dir / ("camera_rom_id_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".log")
    with path.open("x", encoding="utf-8") as log:
        def emit(line):
            print(line, flush=True);log.write(line + "\n");log.flush()
        emit("ESP-A port: " + port)
        code = identify(port, emit=emit)
    print("Raw log: " + str(path))
    return code


if __name__ == "__main__":raise SystemExit(main())
