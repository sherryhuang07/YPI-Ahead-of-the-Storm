$path = Join-Path $PSScriptRoot 'outputs/prospective/scoreboard.json'
if (-not (Test-Path $path)) { Write-Host 'The first daily check has not finished.'; return }
$score = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
$run = Get-Content (Join-Path $PSScriptRoot 'outputs/prospective/last-run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host 'DAILY FORECAST CHECK - NO LOOKING AHEAD' -ForegroundColor Cyan
Write-Host 'Daily schedule (Connecticut time): 12:05 AM rainfall, wells and soil moisture; 6:30 AM stream gauges. Computer must be on and signed in.'
Write-Host "Last completed check (UTC): $($run.completed_at)"
Write-Host 'Original predictions are timestamped and kept. Later readings only score them.'
Write-Host ('New comparisons scored in this check: {0}.' -f $run.new_comparisons)
if ($run.source_errors.Count) {
    Write-Host 'Some live data downloads failed. Missing readings stay unscored; no values are filled in.' -ForegroundColor Yellow
} else {
    Write-Host 'Live inputs were retrieved for this check.'
}
foreach ($kind in @('precipitation','groundwater','streamflow')) {
    $latest = @($score.issues | Where-Object { $_.variable -eq $kind } | Sort-Object issued_at | Select-Object -Last 1)
    if ($latest.Count) {
        Write-Host "`n$kind - latest issue: $($latest[0].issued_at) UTC" -ForegroundColor Green
        $issueFiles = Get-ChildItem (Join-Path $PSScriptRoot "outputs/prospective/issued/$($latest[0].day)") -Filter '*.json'
        $record = $null
        foreach ($issueFile in $issueFiles) {
            $candidate = Get-Content $issueFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($candidate.issued_at -eq $latest[0].issued_at -and $candidate.variable -eq $kind) {
                $record = $candidate
                Write-Host "Locations forecast: $(@($record.forecasts).Count). Withheld: $(@($record.unavailable).Count)."
                foreach ($missing in $record.unavailable) { Write-Host "$($missing.id): $($missing.reason)" -ForegroundColor Yellow }
                break
            }
        }
        if ($kind -eq 'groundwater' -and $record -and $record.variable -eq 'groundwater') {
            $wellForecasts = @($record.forecasts)
            if ($wellForecasts.Count) {
                Write-Host "`nTwo-week estimates for $($wellForecasts.Count) monitored wells: $($wellForecasts[0].dates[0]) through $($wellForecasts[0].dates[-1])" -ForegroundColor Cyan
                Write-Host 'Numbers are feet below ground at each well. A larger number means the water level is lower.'
                Write-Host 'Well                                               First day   Last day   Expected direction'
                foreach ($well in $wellForecasts) {
                    $first = [double]$well.prediction[0]
                    $last = [double]$well.prediction[-1]
                    $change = $last - $first
                    if ($change -gt 0.05) { $direction = 'Lower water level' }
                    elseif ($change -lt -0.05) { $direction = 'Higher water level' }
                    else { $direction = 'About unchanged' }
                    Write-Host ('{0,-50} {1,8:N2}   {2,8:N2}   {3}' -f $well.name,$first,$last,$direction)
                }
                Write-Host 'This is an experimental well-level forecast, not a measurement beneath any farm.' -ForegroundColor Yellow
                Write-Host 'Prediction ranges are not calibrated yet; hundredths are display precision, not proven accuracy.'
            }
            $blindRoot = Join-Path $PSScriptRoot 'outputs/forecasts/groundwater/blind-hindcast'
            $blindScorecards = @(Get-ChildItem -LiteralPath $blindRoot -Filter 'scorecard.json' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName)
            if ($blindScorecards.Count) {
                $blindStudy = Get-Content $blindScorecards[-1].FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                Write-Host "`nBlind historical replay ($($blindStudy.training_period_for_method_selection[0]) to $($blindStudy.training_period_for_method_selection[1]) used to choose methods; test issues $($blindStudy.test_issue_period[0]) to $($blindStudy.test_issue_period[1])):" -ForegroundColor Cyan
                Write-Host ('Average error: {0:N2} feet; simple last-reading comparison: {1:N2} feet; better at {2} of {3} wells.' -f $blindStudy.mean_station_forecast_mae_ft,$blindStudy.mean_station_persistence_mae_ft,$blindStudy.wells_beating_persistence,$blindStudy.wells_with_scores)
                $dayOne = $blindStudy.by_forecast_day | Where-Object { $_.forecast_day -eq 1 } | Select-Object -First 1
                $daySeven = $blindStudy.by_forecast_day | Where-Object { $_.forecast_day -eq 7 } | Select-Object -First 1
                $dayFourteen = $blindStudy.by_forecast_day | Where-Object { $_.forecast_day -eq 14 } | Select-Object -First 1
                if ($dayOne -and $daySeven -and $dayFourteen) {
                    Write-Host ('Error by lead day (model / simple comparison): day 1 {0:N2}/{1:N2} ft; day 7 {2:N2}/{3:N2} ft; day 14 {4:N2}/{5:N2} ft.' -f $dayOne.forecast_mae_ft,$dayOne.persistence_mae_ft,$daySeven.forecast_mae_ft,$daySeven.persistence_mae_ft,$dayFourteen.forecast_mae_ft,$dayFourteen.persistence_mae_ft)
                }
                Write-Host 'Forecasts were saved before test readings were opened. Historical USGS values may include later revisions; this is not a real-time-vintage replay.' -ForegroundColor Yellow
                Write-Host 'The current sealed forecast above is still waiting for its target readings.' -ForegroundColor Yellow
            } elseif (Test-Path -LiteralPath $blindRoot) {
                Write-Host "`nBlind replay forecasts are sealed; the separate scorecard is not available yet." -ForegroundColor Yellow
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
if ($run.source_errors.Count) {
    Write-Host 'Data sources that could not be reached:' -ForegroundColor Yellow
    foreach ($errorText in $run.source_errors) {
        if ($errorText -match 'api\.waterdata\.usgs\.gov') { Write-Host 'USGS daily water observations: download failed.' -ForegroundColor Yellow }
        elseif ($errorText -match 'services\.nacse\.org') { Write-Host 'PRISM precipitation history: download failed.' -ForegroundColor Yellow }
        elseif ($errorText -match 'NOAA NBM|nomads\.ncep\.noaa\.gov') { Write-Host 'NOAA live precipitation guidance: download failed.' -ForegroundColor Yellow }
        else { Write-Host 'A data source download failed.' -ForegroundColor Yellow }
    }
}
$rzBoard = Join-Path $PSScriptRoot 'outputs/root-zone-prospective/scoreboard.json'
$rzRun = Join-Path $PSScriptRoot 'outputs/root-zone-prospective/last-run.json'
if ((Test-Path -LiteralPath $rzBoard) -and (Test-Path -LiteralPath $rzRun)) {
    $rz = Get-Content -LiteralPath $rzBoard -Raw -Encoding UTF8 | ConvertFrom-Json
    $rzLast = Get-Content -LiteralPath $rzRun -Raw -Encoding UTF8 | ConvertFrom-Json
    $rzIssue = @($rz.issues | Sort-Object issued_at | Select-Object -Last 1)
    Write-Host "`nroot-zone soil moisture - separate ledger" -ForegroundColor Green
    if ($rzIssue.Count) { Write-Host "Latest issue: $($rzIssue[0].issued_at) UTC (Connecticut day $($rzIssue[0].day))." }
    Write-Host ('Watersheds forecast: {0}. Withheld: {1}. NASA NLDAS inputs {2} through {3}.' -f $rzLast.available_forecasts,$rzLast.unavailable_forecasts,$rzLast.input_window[0],$rzLast.input_window[1])
    $rzMetrics = @($rz.by_variable_and_lead | Where-Object { $_.variable -eq 'root-zone' })
    if (-not $rzMetrics.Count) {
        Write-Host 'Waiting for target days to pass and NASA data to arrive (about four days behind). No accuracy score yet.'
    } else {
        Write-Host 'Forecast day   Comparisons   Average error (pct points)   Unchanged-moisture error'
        foreach ($m in $rzMetrics) { Write-Host ('{0,12}   {1,11}   {2,26:N2}   {3,24:N2}' -f $m.forecast_day,$m.comparisons,($m.mae*100),($m.baseline_mae*100)) }
        if ($null -ne $rz.interval.coverage) { Write-Host ('Observed values inside the nominal 90% band: {0:P0} of {1}.' -f $rz.interval.coverage,$rz.interval.scored) }
    }
    Write-Host 'Scores compare with NASA modeled watershed moisture, not farm sensors.'
}
$learnRoot = Join-Path $PSScriptRoot 'outputs/learning'
if (Test-Path -LiteralPath $learnRoot) {
    Write-Host "`nLEARNING VERSIONS - original vs learning, same target days" -ForegroundColor Cyan
    Write-Host 'Each day, before forecasting, the learning version updates its weights from newly scored comparisons. Originals stay fixed.'
    foreach ($m in @('precipitation','groundwater','streamflow','regional-streamflow','root-zone','fire-danger','water-temp','drought')) {
        $lr = Join-Path $learnRoot "$m/last-run.json"; $lb = Join-Path $learnRoot "$m/scoreboard.json"
        if (-not (Test-Path -LiteralPath $lr)) { continue }
        $run = Get-Content -LiteralPath $lr -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ("{0}: learned from {1} scored comparisons so far; today: {2}." -f $m,$run.total_comparisons_learned,$run.issued)
        if (Test-Path -LiteralPath $lb) {
            $b = Get-Content -LiteralPath $lb -Raw -Encoding UTF8 | ConvertFrom-Json
            $rowsL = @($b.by_variable_and_lead | Where-Object { $_.forecast_day -in 1,7,14 })
            if (-not $rowsL.Count) { Write-Host '  No learning forecast scored yet.' }
            foreach ($r in $rowsL) { Write-Host ('  Day {0}: learning error {1:N3} vs original {2:N3} ({3} comparisons)' -f $r.forecast_day,$r.mae,$r.baseline_mae,$r.comparisons) }
        }
    }
    Write-Host 'Errors are in each model''s units (rain mm, well feet, flow cfs, soil water m3/m3, fire danger classes, water degrees C, drought DSCI 0-500). Early results are few and correlated.'
}
