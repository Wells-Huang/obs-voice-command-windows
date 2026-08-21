[CmdletBinding()]
param(
    [switch]$CheckCli,
    [switch]$Json,
    [string]$CodexBin = "codex"
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "validate_model_routing.py"
$arguments = @($scriptPath)
if ($CheckCli) {
    $arguments += "--check-cli"
    $arguments += "--codex-bin"
    $arguments += $CodexBin
}
if ($Json) {
    $arguments += "--json"
}

$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
    & $bundledPython @arguments
    exit $LASTEXITCODE
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source @arguments
    exit $LASTEXITCODE
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & $pyLauncher.Source -3.12 @arguments
    exit $LASTEXITCODE
}

Write-Error "Python 3.12 or the Codex bundled Python runtime is required."
exit 1
