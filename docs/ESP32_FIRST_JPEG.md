# First genuine ESP32-camera JPEG: future evidence workflow

**No camera JPEG, sensor PID, initialization or continuous feed was verified in this release pass.** Read [hardware setup](HARDWARE_SETUP.md) for the reported arrangement, electrical unknowns and all ten required milestones. No hardware operation or serial-port opening is authorized by this guide.

## Before a physical session

Establish the carrier revision, sensor and GPIO map, safe supply/current budget, programming route and boot/reset routing. Preserve the primary telemetry firmware and recovery copy. The current source does not forward camera images. A diagnostic UART responder is not capture firmware; the compiled bridge is not a physically tested programmer. The camera-capture reference is inert. The separately preserved AI-Thinker hypothesis is not a verified target.

Older direct-adapter/IO0/EN procedures remain in [the historical snapshot](history/ESP32_FIRST_JPEG_2026-10-20.md). They describe a different reported setup and must not be applied as current wiring instructions. The primary GPIO17/GPIO16 arrangement in the latest requirements has not been electrically checked. No blind pin short, supply change or serial command is appropriate while routing and power remain unresolved.

## Evidence to collect after prerequisites and separate authorization

| Stage | Required genuine evidence | Does not establish |
| --- | --- | --- |
| Programming/ROM path | Verified responding device identity, actual tool output and known target origin | Camera sensor identity or capture |
| Driver initialization | Real initialization result and sensor PID read by the driver | Parallel data pin correctness or a JPEG |
| Capture | Actual encoded JPEG bytes from camera firmware, valid packet length and checksum | That the host can decode or display it |
| Host reception | Decoded dimensions, timestamp, device identity, image hash and source provenance | Continuous frame delivery |
| Continuous transport | Measured counts, elapsed span, age, gaps, reconnections and bounded-buffer drops | Detector/event accuracy |
| Application | Genuine source frame in dashboard, detector/tracker processing, source-linked event/evidence and separate model results | Identity, intent or guaranteed interpretation |

Record failures and missing stages as failures or unknowns. Boot text is not a PONG. A firmware-reported PID remains a device report until origin is established. A checksum is integrity evidence, not authentication. The host first-JPEG receiver cannot generate an image when none is sent.

## Prepared software

The SNC1 host implementation handles bounded partial reads, CRC checks, JPEG decode, timeout/reconnection and a latest-frame buffer. Automated serial/image tests use synthetic bytes and mocked ports; they prove protocol behavior only. The gated `esp32/camera_capture` implementation requires locally verified deployment configuration before a real build. That configuration is excluded from Git.

The existing `CameraSource` can receive an explicitly configured HTTP MJPEG stream without changing the AI pipeline. A URL does not prove it belongs to an ESP32. UART throughput and Wi-Fi behavior must be measured on the verified setup; no camera FPS is promised.

Use [the laptop demonstration](DEMO_GUIDE.md) now. Physical camera work remains blocked pending electrical assessment, supported programming and separately authorized testing.
