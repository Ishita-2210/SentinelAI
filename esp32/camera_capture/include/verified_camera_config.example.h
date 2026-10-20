#pragma once
#error "Do not compile for hardware until this actual carrier, sensor, power and pin map are verified."
// After independent verification, provide a PRIVATE verified_camera_config.h.
// It must define all four values as1 only when physically justified:
// SENTINEL_POWER_VERIFIED, SENTINEL_PINMAP_VERIFIED,
// SENTINEL_PROGRAMMING_VERIFIED, SENTINEL_UART0_VERIFIED.
// It must implement: camera_config_t verifiedCameraConfig();
// Set every camera pin from the actual matched schematic, not a reference guess.
// Configure JPEG, one framebuffer, validated frame-size/quality/clock/memory.
// Keep UART0 GPIO1/3 free; release IO0 download strap for normal operation.
// No pin values or sensor PID are supplied by this template.
