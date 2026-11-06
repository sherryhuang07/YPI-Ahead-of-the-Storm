# Daily 14-day test forecasts for every isolated model, each in its own sealed ledger:
#   1. prospective_daily.py  - precipitation baseline, groundwater wells, CT stream gauges (+ NOAA NBM archive)
#   2. regional_daily.py     - connected neighboring-state stream gauges
#   3. root-zone-update.ps1 -Step daily - root-zone soil moisture (NASA NLDAS-2 inputs)
# Jobs run independently; one failure never blocks or alters the others. Re-running on the
# same Connecticut day refreshes observations and scores but never replaces a sealed forecast.
# Reservoir capacity has no daily public feed, so it has no daily forecast (see RESERVOIRS.md).
param([switch]$Scheduled, [switch]$Force)
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$ctNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
if ($Scheduled) {
    $logDir = Join-Path $root 'outputs\daily-run-logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Transcript -LiteralPath (Join-Path $logDir ($ctNow.ToString('yyyy-MM-dd_HHmm') + '.log')) -Append | Out-Null
}
# Each variable gets one sealed issue per Connecticut day. Before about 5 AM, yesterday's USGS
# readings are usually unpublished, so streamflow would be withheld for the whole day; after
# 10 PM a run could cross midnight partway through. Only run inside 5:00 AM - 10:00 PM.
if (($ctNow.Hour -lt 5 -or $ctNow.Hour -ge 22) -and -not $Force) {
    $msg = 'Skipped: it is ' + $ctNow.ToString('HH:mm') + ' in Connecticut. Daily forecasts run between 5:00 AM and 10:00 PM (use -Force to override).'
    Write-Host $msg -ForegroundColor Yellow
    Add-Content -LiteralPath (Join-Path $root 'activity.log') -Value ((Get-Date).ToUniversalTime().ToString('o') + ' | Daily forecasts: ' + $msg) -Encoding utf8
    if ($Scheduled) { Stop-Transcript | Out-Null }
    exit 0
}
$python = Join-Path $root '.venv\Scripts\python.exe'
$jobs = @(
    @{ name = 'Precipitation, groundwater wells and CT streamflow'; run = { & $python (Join-Path $root 'scripts\prospective_daily.py') } },
    @{ name = 'Neighboring-state stream gauges'; run = { & $python (Join-Path $root 'scripts\regional_daily.py') } },
    @{ name = 'Root-zone soil moisture'; run = { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'root-zone-update.ps1') -Step daily } }
)
$results = @()
Push-Location $root
try {
    foreach ($job in $jobs) {
        Write-Host ''
        Write-Host ('=== ' + $job.name + ' ===') -ForegroundColor Cyan
        $started = (Get-Date).ToUniversalTime()
        try { & $job.run; $code = $LASTEXITCODE } catch { Write-Host $_.Exception.Message -ForegroundColor Red; $code = 1 }
        if ($null -eq $code) { $code = 0 }
        $status = if ($code -eq 0) { 'ok' } else { 'failed (exit ' + $code + ')' }
        Write-Host ($job.name + ': ' + $status) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
        $results += [pscustomobject]@{ job = $job.name; started_at = $started.ToString('o'); exit_code = $code; status = $status }
    }
} finally { Pop-Location }
$summary = [pscustomobject]@{ completed_at = (Get-Date).ToUniversalTime().ToString('o'); jobs = $results }
$summaryPath = Join-Path $root 'outputs\daily-run-summary.json'
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding utf8
$failed = @($results | Where-Object { $_.exit_code -ne 0 })
$line = (Get-Date).ToUniversalTime().ToString('o') + ' | Daily forecasts: ' + ($results.Count - $failed.Count) + ' of ' + $results.Count + ' jobs ok' + $(if ($failed.Count) { '; failed: ' + (($failed | ForEach-Object { $_.job }) -join ', ') } else { '' })
Add-Content -LiteralPath (Join-Path $root 'activity.log') -Value $line -Encoding utf8
Write-Host ''
Write-Host $line
if ($Scheduled) { Stop-Transcript | Out-Null }
exit $(if ($failed.Count) { 1 } else { 0 })
