$ErrorActionPreference = 'Stop'
$activityPath = Join-Path $PSScriptRoot 'activity.log'
if (-not (Test-Path -LiteralPath $activityPath)) {
    New-Item -ItemType File -Path $activityPath | Out-Null
}
foreach ($view in @('farmer-view.ps1', 'behind-the-scenes.ps1')) {
    $scriptPath = Join-Path $PSScriptRoot $view
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $scriptPath + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Normal
}
