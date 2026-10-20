**ESP32 camera integration is experimental. Physical sensor initialization, firmware flashing, genuine JPEG reception, continuous video, dashboard display, and AI processing of real ESP32-origin frames have not been verified end to end.**

Official presentation: laptop webcam via `& D:\SentinelAI\scripts\run_presentation.ps1 -Source 0`. Keep the hardware unpowered; the instructions below are retained for future separately authorized work after electrical inspection.

> **Current hardware hold:** the user reports CAM became very hot during a 3V3 power experiment and has no multimeter. Keep the camera/DevKit assembly unpowered pending competent electrical inspection. All earlier manual serial/ROM/flash/reset and supply-comparison instructions below are suspended for the current assembly. No new hardware action is authorized by the presentation work. A prior adapter loopback passed, but CAM power, ROM, sensor and JPEG remain unverified.

# ESP-A direct USB-UART: ROM ID, then first JPEG

This baseline supersedes the GPIO16/17 firmware-relay plan. No ESP-A flash change is required or proposed. `scripts/uart_programmer_bridge.py` remains as legacy code; its `--serve` CLI is disabled for this baseline. Runtime capture remains unverified, and ROM ID is a separate explicitly authorized manual operation, not a preflight action.

## 1. Already available

The project `.venv` contains esptool **5.6.0**; PlatformIO has its own build tool version. Use the project Python below. `scripts/camera_chip_id.ps1` selects the unique CH9102 VID1A86/PID55D4 port, or accepts `-Port COMn` after Device Manager confirmation. It runs only `chip-id`, then `flash-id` if the first succeeds. Both use `--chip esp32 --baud 115200 --before no-reset --after no-reset --no-stub`. No upload, erase, RAM stub or auto-reset is performed. Raw output is printed and saved under ignored `data/hardware_identification/camera_rom_id_*.log`.

Existing exact-JPEG export, SNC1 CRC/partial-read receiver and pipeline integration remain available. Webcam presentation defaults and SentinelTelemetry/recovery files are preserved. No port has been opened by this update.

## 2. Manual download-mode procedure and command

Close serial monitors before running the test. Confirm ESP-A's port in **Device Manager > Ports (COM & LPT)**; COM9 is historical, not assumed current.

Keep ESP-A EN-GND installed. Keep CAM IO0-GND installed **only for download mode**. Press and release the CAM reset button with IO0 held low, then run the command; resetting the CAM is sufficient and avoids removing its supply while UART is attached. If a power-cycle is necessary instead: disconnect both laptop USB and bank USB first to avoid an energized UART feeding an unpowered board, retain the reported jumpers, reconnect bank USB then ESP-A USB, and confirm the port again. This is an operator procedure, not an automatically executed action or a certification of the supply path.

```powershell
Set-Location D:\SentinelAI
& .\scripts\camera_chip_id.ps1 -Port COM9
```

Substitute the actual Device Manager port if different; omit `-Port` only if there is exactly one CH9102 candidate. Exact underlying commands (do not run these as well as the script):

```powershell
& .\.venv\Scripts\python.exe -m esptool --chip esp32 --port COM9 --baud 115200 --before no-reset --after no-reset --no-stub chip-id
if ($LASTEXITCODE -eq 0) {
    & .\.venv\Scripts\python.exe -m esptool --chip esp32 --port COM9 --baud 115200 --before no-reset --after no-reset --no-stub flash-id
}
```

`no-reset` is esptool5's spelling of the older `no_reset`; `chip-id` replaces `chip_id`. Expected success includes ESP32 identification/MAC (ESP32 has no separate chip-ID value), flash manufacturer/device/capacity, and the script PASS line. The two read commands leave CAM in the ROM loader. Copy the **entire output**, including MAC, flash capacity, warnings and PASS/FAIL. A matching known ESP-A MAC means the responding chip may be ESP-A: EN-low/origin must then be checked. Same ESP32 family alone cannot distinguish the two devices.

## 3. Current reported wiring (corrected adapter direction)

| Reported connection | Role |
|---|---|
| ESP-A RX0/GPIO3 -> CAM U0R | CH9102 transmit path to CAM receive; reported, not yet ROM-tested |
| ESP-A TX0/GPIO1 <- CAM U0T | CAM transmit to CH9102 receive; reported, not yet ROM-tested |
| ESP-A GND -> ESP-B GND -> CAM GND | Common reference through ESP-B |
| ESP-A EN -> ESP-A GND | Holds ESP-A's CPU reset; CH9102 can operate independently if board routing supports it |
| CAM IO0 -> CAM GND | Temporary download strap |
| ESP-B5V -> CAM5V; ESP-B USB -> power bank | Camera's only reported positive supply; current budget not measured |
| CAM reset button | Manual reset, not controlled by DTR/RTS |

Old GPIO16/17 wires are removed; no shared3V3 or ESP-A positive rail is reported. Firmware relay ARM commands must not be sent to CAM. ESP-A telemetry is temporarily stopped by EN-low but its flash is untouched; restoring it later requires removing EN-GND **and isolating CAM UART from those shared pins first** to prevent two active ESP32 transmitters driving the same CH9102 net.

The new reported adapter direction matches the common USB-UART net orientation: USB-UART TX reaches ESP32 RX0/GPIO3, and USB-UART RX reaches ESP32 TX0/GPIO1. The preceding manual run (`camera_rom_id_20261020_180733_849295.log`) opened COM9 but returned **No serial data received**; flash ID was not attempted. That run used the previous reversed pair. The failure is consistent with incorrect direction but does not prove its cause. The corrected wiring has not yet passed chip ID. COM9 CH9102 enumeration was observed in the supplied output; no sensor or JPEG result exists.

## 4. Ranked checklist for No serial data received

The script prints this checklist only for that failure and never retries automatically:

1. **IO0 not low at reset:** keep CAM IO0-GND in place and press/release CAM reset, not ESP-A reset.
2. **Wrong/loose camera UART pins:** check ESP-A GPIO3/RX0 -> CAM U0R and GPIO1/TX0 <- CAM U0T, connector contact, and common ground through ESP-B. Do not reverse the corrected pair based only on another timeout.
3. **Weak/unstable CAM5V:** measure CAM input/3V3 under load. A source comparison may use ESP-A5V as the sole CAM supply **only after its USB5V path and current capacity are established**. Power everything off first, remove ESP-B5V->CAM5V before adding ESP-A5V->CAM5V, retain common GND, and never join both positive supplies. ESP-A's capacity is not established by its label or this failed log; this alternative is not an automatically approved supply upgrade.
4. **ESP-A EN not held low:** its own ESP32 may drive the shared UART. Keep EN-GND installed; do not alter its firmware.
5. **Wrong/busy port:** confirm COM9 still belongs to ESP-A in Device Manager and close serial monitors. Access-denied errors point here first; no-data errors mean the port opened but no serial reply was received.

Optional manual **ESP-A-only loopback**: with all sources off, disconnect both CAM UART wires so CAM is isolated from TX/RX, retain ESP-A EN-GND, and jumper ESP-A RX0/GPIO3 to TX0/GPIO1. Power only ESP-A USB, open a terminal at1152008N1, disable flow control and **local echo**, and send characters. Only returned/received characters count as loopback evidence. Close the terminal before any esptool run; power off before removing loopback/restoring CAM wiring. This tests the adapter path without CAM; it does not prove CAM power, boot, sensor or JPEG. It is optional manual troubleshooting, not an additional operation performed by this script/agent.

For invalid-packet/apparent-baud errors keep115200 and check contact, contention and supply before increasing speed. Wrong-boot-mode means CAM straps/reset need checking; wrong-chip/MAC must be reported without flashing. If chip ID passes but flash ID fails, stop and paste both outputs; do not guess flash size or erase.

A PASS supports a working powered ROM/UART/download path at that moment **only if CAM origin is established**. It does not certify the supply margin, sensor, full camera pin map or JPEG capture. No new serial run has been performed by the agent.

## 5. Next milestone: explicitly hypothetical one-JPEG firmware

`esp32/camera_first_jpeg_hypothesis` is a separate compiled `esp32cam`/AI-Thinker hypothesis, not a claim of carrier identification. Its source selects the official AI-Thinker pins, prints `INIT code=...`, actual driver-read `SENSOR PID=...` and device ID, waits8seconds for a receiver, then emits one QVGA JPEG as SNC1 status+JPEG packets. It uses DRAM and one buffer, avoids needing assumed PSRAM capacity, caps JPEG at128KiB, reports errors and retains a bounded PING responder. It does not start Wi-Fi or the flash LED. Build only:

```powershell
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_first_jpeg_hypothesis
```

**Do not flash until chip ID results are reviewed and you confirm the next step.** No upload command is included. Before normal capture, remove CAM IO0-GND and reset CAM; this hypothesis uses GPIO0 as XCLK. Start the receiver before that reset so the single emitted frame is not missed. A valid PID supports sensor/SCCB recognition; it does not alone prove the parallel data map. A valid decoded JPEG provides the next evidence for that configuration. A failed init does not by itself prove a bad sensor or definitively reject the map: power, ribbon contact and clock also matter.

## 6. Video transport choice

Prefer **Wi-Fi MJPEG for ongoing video**, UART for programming and diagnostics. At1152008N1 the UART payload ceiling is11520bytes/s. For a20KiB JPEG plus32byte header:

| Link | Ideal transport ceiling | Planning range, not measured |
|---|---:|---:|
| UART115200 |0.56fps|about0.3-0.5fps|
| UART921600 |4.49fps|about2-4fps|
| UART2Mbps |9.75fps|about4-8fps; adapter/cable support unverified|
| Wi-Fi MJPEG |6.1-30.5fps at1-5Mbit/s useful JPEG throughput|target5-15fps at QVGA/VGA, then measure|

These are calculations/engineering estimates, not sensor benchmarks. JPEG size, sensor, RF, buffering and CPU change results; halve frame size to roughly double the UART ceiling. The existing prepared UART source is fixed115200; higher rates require coordinated firmware/host changes and validation, not just a CLI baud change.

Host design reuses `open/read_frame/close`: `Esp32CameraSource` for framed UART; existing `CameraSource` for HTTP MJPEG with bounded network timeouts/reconnect. The launcher now accepts an explicit `http://CAM-IP:81/stream` URL without trying to open it in preflight, keeps serial disabled, and feeds the same YOLO/ByteTrack/events/evidence/asynchronous VLM/LLM path. It labels this **network_stream**, not verified ESP32, until device identity/origin is established; an arbitrary URL is not origin proof. Wi-Fi streaming firmware is the stage after the first JPEG, not installed now. No SSID/password is stored in tracked source.

Sources: [Espressif reference USB-UART wiring](https://dl.espressif.com/dl/schematics/esp32_devkitc_v4_sch.pdf), [manual ROM boot selection](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html), [official camera pin maps](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h).


Validation for this update: all76 relevant offline tests passed across the focused runs (one obsolete error-message assertion was updated for the new baseline). The hypothetical capture firmware built successfully:34236bytes RAM,394849bytes application. Original telemetry/recovery hashes were rechecked and unchanged. No chip-ID command, serial opening, reset, flash or erase was performed by the agent; sensor PID/JPEG remain unreceived. No completed full-suite or legacy firmware build was repeated.
