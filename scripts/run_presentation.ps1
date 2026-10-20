[CmdletBinding()]
param(
    [string]$Source = "data/demo/webcam.avi",
    [switch]$NoVLM,
    [switch]$NoLLM,
    [switch]$NoLoop,
    [switch]$Check,
    [ValidateRange(0, 86400)][double]$MaxSeconds = 0
)
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Project virtual environment missing: $pythonExe" }
$launchArgs = @((Join-Path $PSScriptRoot "presentation.py"), "--source", $Source)
if ($NoVLM) { $launchArgs += "--no-vlm" }
if ($NoLLM) { $launchArgs += "--no-llm" }
if ($NoLoop) { $launchArgs += "--no-loop" }
if ($Check) { $launchArgs += "--check" }
if ($MaxSeconds -gt 0) { $launchArgs += @("--max-seconds", $MaxSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)) }
Push-Location $projectRoot
try {
    & $pythonExe @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "Presentation exited with code $LASTEXITCODE. Inspect the log printed above." }
} finally { Pop-Location }
