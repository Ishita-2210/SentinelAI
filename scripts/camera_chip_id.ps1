[CmdletBinding()]
param([string]$Port)
# Manual operator command only. Never called by tests, preflight or presentation.
# ESP-A EN-GND; RX0/GPIO3->CAM U0R; TX0/GPIO1<-CAM U0T.
# ESP-A GND->ESP-B GND->CAM GND; ESP-B5V->CAM5V; CAM IO0-GND for download.
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$arguments = @((Join-Path $PSScriptRoot "camera_chip_id.py"))
if ($Port) { $arguments += @("--port", $Port) }
& $pythonExe @arguments
exit $LASTEXITCODE
