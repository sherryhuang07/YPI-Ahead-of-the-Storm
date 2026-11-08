# Daily 14-day test forecasts for every isolated model, each in its own sealed ledger.
#
#   -Part night   (scheduled 12:05 AM): precipitation baseline + NOAA NBM archive, groundwater
#                 wells, root-zone soil moisture. None of these needs yesterday's readings.
#   -Part morning (scheduled 6:30 AM):  Connecticut stream gauges and neighboring-state gauges.
#                 The frozen streamflow models need yesterday's USGS daily reading, which is
#                 not published around midnight.
#   -Part all     (manual default):     everything, morning hours only.
#
# Jobs run independently; one failure never blocks or alters the others. Each variable gets one
# sealed issue per Connecticut day; re-running refreshes observations and scores but never
# replaces a sealed forecast. Each part ends with the learning versions of its models
# (scripts/learning_daily.py), which update their weights from newly scored comparisons first.
# Reservoir capacity has no daily public feed (see RESERVOIRS.md).
param([ValidateSet('all','night','morning')][string]$Part = 'all', [switch]$Scheduled, [switch]$Force)
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$ctNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
$logDir = Join-Path $root 'outputs\daily-run-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
# First thing: record that this run started, so a run killed in its first seconds still leaves a trace.
Add-Content -LiteralPath (Join-Path $logDir 'run-starts.log') -Value ('{0} | {1} part | scheduled={2} | pid {3}' -f (Get-Date).ToUniversalTime().ToString('o'), $Part, [bool]$Scheduled, $PID) -Encoding utf8
if ($Scheduled) {
    Start-Transcript -LiteralPath (Join-Path $logDir ($ctNow.ToString('yyyy-MM-dd_HHmm') + '-' + $Part + '.log')) -Append | Out-Null
}
# Allowed Connecticut hours. After 10 PM any run could cross midnight partway through.
# Streamflow (morning/all) must also wait until 5 AM for yesterday's USGS readings.
$earliest = if ($Part -eq 'night') { 0 } else { 5 }
if (($ctNow.Hour -lt $earliest -or $ctNow.Hour -ge 22) -and -not $Force) {
    $msg = 'Skipped ' + $Part + ' run: it is ' + $ctNow.ToString('HH:mm') + ' in Connecticut. Allowed from ' + $earliest + ':00 to 22:00 (use -Force to override).'
    Write-Host $msg -ForegroundColor Yellow
    Add-Content -LiteralPath (Join-Path $root 'activity.log') -Value ((Get-Date).ToUniversalTime().ToString('o') + ' | Daily forecasts: ' + $msg) -Encoding utf8
    if ($Scheduled) { Stop-Transcript | Out-Null }
    exit 0
}
# Only one part at a time: night and morning share the forecast database. Wait up to 2 hours.
$lock = New-Object System.Threading.Mutex($false, 'Global\AheadOfTheStormDailyForecasts')
try { $haveLock = $lock.WaitOne([TimeSpan]::FromHours(2)) } catch [System.Threading.AbandonedMutexException] { $haveLock = $true }
if (-not $haveLock) { Write-Host 'Another forecast run is still going after 2 hours; stopping.' -ForegroundColor Yellow; if ($Scheduled) { Stop-Transcript | Out-Null }; exit 1 }
# A scheduled run waits a minute first: when the laptop wakes only briefly to hibernate, Task
# Scheduler starts missed runs in those seconds; this way they stop before doing anything.
if ($Scheduled -and -not $Force) { Start-Sleep -Seconds 60 }
$ctNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
# Scheduled retries: a part that already finished without failures today exits at once.
# (Forecasts are sealed once per Connecticut day anyway; this just avoids repeating downloads.)
$summaryPath = Join-Path $root ('outputs\daily-run-summary-' + $Part + '.json')
if ($Scheduled -and -not $Force -and (Test-Path -LiteralPath $summaryPath)) {
    try {
        $prev = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        $prevCt = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(([DateTime]::Parse($prev.completed_at)).ToUniversalTime(), 'Eastern Standard Time')
        if ($prevCt.Date -eq $ctNow.Date -and -not @($prev.jobs | Where-Object { $_.exit_code -ne 0 }).Count) {
            Write-Host ('The ' + $Part + ' part already completed today at ' + $prevCt.ToString('HH:mm') + '; nothing to do.')
            Stop-Transcript | Out-Null
            exit 0
        }
    } catch { Write-Host 'Could not read the previous run summary; running anyway.' }
}
$prospective = Join-Path $root 'scripts\prospective_daily.py'
$learning = Join-Path $root 'scripts\learning_daily.py'
$nightJobs = @(
    @{ name = 'Precipitation and groundwater wells (+ NOAA NBM)'; run = { & $python $prospective --only precipitation groundwater } },
    @{ name = 'Root-zone soil moisture'; run = { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'root-zone-update.ps1') -Step daily } },
    # Fire danger: archive DEEP's latest rating (the target), refresh recent airport weather,
    # rebuild the index history, then seal the 14-day forecast. Each step stops the chain if it fails.
    @{ name = 'Fire danger'; run = {
        $fire = @(@('fetch_fire_danger_reports.py'), @('fetch_fire_weather.py','--merge-days','45'), @('build_fire_danger_history.py'), @('fire_danger_daily.py'))
        $global:LASTEXITCODE = 0
        foreach ($step in $fire) {
            & $python (Join-Path $root ('scripts\' + $step[0])) @($step | Select-Object -Skip 1)
            if ($LASTEXITCODE -ne 0) { Write-Host ('Fire danger step failed: ' + $step[0]) -ForegroundColor Yellow; break }
        } } },
    # Coastal water temperature: refresh recent NDBC readings, then seal the 14-day forecast.
    @{ name = 'Coastal water temperature'; run = {
        & $python (Join-Path $root 'scripts\fetch_water_temp.py') --recent
        if ($LASTEXITCODE -eq 0) { & $python (Join-Path $root 'scripts\water_temp_daily.py') } } },
    # Combined drought forecast: runs after every input above is refreshed. Refreshes Palmer and the
    # Drought Monitor, then seals the next two weekly maps for the state and its 9 planning regions.
    @{ name = 'Combined drought forecast'; run = {
        & $python (Join-Path $root 'scripts\fetch_drought_data.py') --recent
        if ($LASTEXITCODE -eq 0) { & $python (Join-Path $root 'scripts\drought_daily.py') } } },
    # drought-v2 = the same forecast plus USGS VegDRI (vegetation stress), in its own ledger. Downloads the
    # newest VegDRI week with the saved USGS sign-in first; if USGS is unreachable, v2 still runs on the last week it has.
    @{ name = 'Combined drought forecast v2 (with VegDRI)'; run = {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'vegdri-update.ps1') -Recent
        if ($LASTEXITCODE -ne 0) { Write-Host 'VegDRI download failed; using the weeks already saved.' -ForegroundColor Yellow }
        & $python (Join-Path $root 'scripts\drought_daily.py') --version v2 } },
    # Learning versions run after the originals: they learn from newly scored comparisons, then correct today's original.
    @{ name = 'Learning versions: precipitation, groundwater, root-zone, fire danger, water temperature, drought v1 and v2'; run = { & $python $learning --models precipitation groundwater root-zone fire-danger water-temp drought drought-v2 } }
)
$morningJobs = @(
    @{ name = 'Connecticut stream gauges'; run = { & $python $prospective --only streamflow --skip-noaa } },
    @{ name = 'Neighboring-state stream gauges'; run = { & $python (Join-Path $root 'scripts\regional_daily.py') } },
    @{ name = 'Learning versions: Connecticut and neighboring stream gauges'; run = { & $python $learning --models streamflow regional-streamflow } },
    # DEEP posts the day's fire danger rating before about 8 AM; a morning capture may get it early.
    @{ name = 'DEEP fire danger rating capture'; run = { & $python (Join-Path $root 'scripts\fetch_fire_danger_reports.py') } }
)
$jobs = switch ($Part) { 'night' { $nightJobs } 'morning' { $morningJobs } default { $nightJobs + $morningJobs } }
# Every part ends by rebuilding the farmer web pages (app/) from the newest sealed forecasts.
$jobs += @{ name = 'Farmer app pages'; run = { & $python (Join-Path $root 'scripts\build_app.py') } }
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
$summary = [pscustomobject]@{ completed_at = (Get-Date).ToUniversalTime().ToString('o'); part = $Part; jobs = $results }
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root ('outputs\daily-run-summary-' + $Part + '.json')) -Encoding utf8
$failed = @($results | Where-Object { $_.exit_code -ne 0 })
$line = (Get-Date).ToUniversalTime().ToString('o') + ' | Daily forecasts (' + $Part + '): ' + ($results.Count - $failed.Count) + ' of ' + $results.Count + ' jobs ok' + $(if ($failed.Count) { '; failed: ' + (($failed | ForEach-Object { $_.job }) -join ', ') } else { '' })
Add-Content -LiteralPath (Join-Path $root 'activity.log') -Value $line -Encoding utf8
Write-Host ''
Write-Host $line
if ($Scheduled) { Stop-Transcript | Out-Null }
exit $(if ($failed.Count) { 1 } else { 0 })
