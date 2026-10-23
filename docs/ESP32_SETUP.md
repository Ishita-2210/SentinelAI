# ESP32 firmware development

Read [hardware setup](HARDWARE_SETUP.md) first: it is the authoritative current wiring record. All physical camera milestones remain unverified. No COM9 access, transmission, flash, erase, reset, power cycle or electrical test is part of this release work.

The latest supplied arrangement uses primary TX2/GPIO17 -> camera U0R, camera U0T -> primary RX2/GPIO16, and common GND. Secondary 5V/GND supplies camera 5V/GND as an unverified intended path. Historical UART0/EN/IO0 experiments are preserved under [history](history/README.md), not instructions for this assembly.

## Preserve the working telemetry path

`esp32/SentinelTelemetry/SentinelTelemetry.ino` provides USB telemetry, ping and software alert acknowledgements. It does not relay images or activate UART2. Preserve this source, the current primary flash and local recovery copies. Do not replace working telemetry to test a camera hypothesis. Historical primary identification does not verify the present flash contents.

## Host tools and compile-only commands

Install the optional tools after the host dependencies:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-verification.txt
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_programmer_bridge
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_capture
```

These commands build only; do not add an upload target. PlatformIO may download its pinned toolchain on first use. `esp32/camera_capture` builds an inert reference, not deployable firmware for this unidentified carrier. The separate `camera_first_jpeg_hypothesis` project contains a guessed AI-Thinker mapping; it is retained as history and must not become a deployment target without independent confirmation. This release does not test that guess.

UART probe and camera responder establish only their nonce-matched diagnostic contract. Compilation does not prove real PING/PONG or sensor initialization. The programming bridge has compiled but is not physically verified as a programmer or stream bridge. Host framing/CRC tests are simulated.

## Future programming route

A supported route requires confirmed board routing, safe power, correct boot control, a reset sequence and the actual camera GPIO map. GPIO0 low during reset selects classic ESP32 download mode, but IO0/reset header routing is unconfirmed. Do not infer pin shorts from a generic diagram. An external programmer may or may not be necessary; examine the available DevKit USB-UART routing and bridge limitations first. No physical command is supplied here while those prerequisites remain unresolved.

After electrical assessment and a separately authorized hardware session, preserve a recovery path, select the confirmed target, install matching capture firmware and collect the staged evidence in [first JPEG](ESP32_FIRST_JPEG.md). A failed ROM response does not diagnose a sensor; a successful build does not approve wiring.

## Current demonstration

```powershell
& .\scripts\run_presentation.ps1 -Source 0
```

Open http://127.0.0.1:8010. The presentation configuration disables telemetry and the webcam/video launcher additionally blocks physical serial opening. Explicit `-Source esp32` fails closed until separate physical approval and diagnostics pass; never use approval flags to bypass missing measurements.
