[CmdletBinding()]
param([switch]$VerifyLaunch)
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonPath = $env:GR_SUBNET_PYTHON
if (-not $pythonPath -and (Test-Path -LiteralPath $bundledPython)) { $pythonPath = $bundledPython }
if (-not $pythonPath) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonPath = $pythonCommand.Source }
}
if (-not $pythonPath) { throw 'Python 3.11 or newer with Tk is required. Set GR_SUBNET_PYTHON to its full path.' }
$windowlessPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $windowlessPython) { $pythonPath = $windowlessPython }
$entryPoint = Join-Path $projectDirectory 'main.py'
$launchArguments = '"' + $entryPoint + '"'
if ($VerifyLaunch) {
    $qaDirectory = Join-Path $projectDirectory 'qa'
    New-Item -ItemType Directory -Force -Path $qaDirectory | Out-Null
    $launchReport = Join-Path $qaDirectory 'launcher-smoke-report.json'
    $launchArguments += ' --verify-launch "' + $launchReport + '"'
}
$launchedProcess = Start-Process -FilePath $pythonPath -ArgumentList $launchArguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru
if ($VerifyLaunch) {
    if (-not $launchedProcess.WaitForExit(10000)) { throw 'The launch verification did not finish.' }
    if ($launchedProcess.ExitCode -ne 0) { throw 'The desktop program failed to launch.' }
    Get-Content -LiteralPath $launchReport
}
