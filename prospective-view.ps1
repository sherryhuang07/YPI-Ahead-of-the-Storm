$path = Join-Path $PSScriptRoot 'outputs/prospective/scoreboard.json'
if (-not (Test-Path $path)) { Write-Host 'The first daily check has not finished.'; return }
$score = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
$run = Get-Content (Join-Path $PSScriptRoot 'outputs/prospective/last-run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host 'DAILY FORECAST CHECK - NO LOOKING AHEAD' -ForegroundColor Cyan
Write-Host 'Daily schedule: 6:00 AM Connecticut time. Computer and app must be running.'
Write-Host "Last completed check (UTC): $($run.completed_at)"
Write-Host 'Original predictions are timestamped and kept. Later readings only score them.'
foreach ($kind in @('precipitation','groundwater','streamflow')) {
    $latest = @($score.issues | Where-Object { $_.variable -eq $kind } | Sort-Object issued_at | Select-Object -Last 1)
    if ($latest.Count) {
        Write-Host "`n$kind - latest issue: $($latest[0].issued_at) UTC" -ForegroundColor Green
        $issueFiles = Get-ChildItem (Join-Path $PSScriptRoot "outputs/prospective/issued/$($latest[0].day)") -Filter '*.json'
        foreach ($issueFile in $issueFiles) {
            $record = Get-Content $issueFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($record.issued_at -eq $latest[0].issued_at -and $record.variable -eq $kind) {
                Write-Host "Locations forecast: $(@($record.forecasts).Count). Withheld: $(@($record.unavailable).Count)."
                foreach ($missing in $record.unavailable) { Write-Host "$($missing.id): $($missing.reason)" -ForegroundColor Yellow }
            }
        }
        $metrics = @($score.by_variable_and_lead | Where-Object { $_.variable -eq $kind })
        if (-not $metrics.Count) { Write-Host 'Waiting for target dates to pass and observations to arrive. No accuracy score yet.' }
        else {
            Write-Host 'Forecast day   Comparisons   Average error   Simple comparison error'
            foreach ($m in $metrics) { Write-Host ('{0,12}   {1,11}   {2,13:N2}   {3,23:N2}' -f $m.forecast_day,$m.comparisons,$m.mae,$m.baseline_mae) }
        }
    }
}
Write-Host "`nUnits: rainfall mm; groundwater feet below land; streamflow cubic feet/second."
Write-Host 'Groundwater is at monitored wells. Farm groundwater and ungauged streams remain unavailable.'
Write-Host 'Neighboring-state stream gauges have a separate forecast archive. See Farmer View option 12.'
if ($run.source_errors.Count) { Write-Host 'Some data could not be updated:' -ForegroundColor Yellow; $run.source_errors | ForEach-Object { Write-Host $_ } }
