Write-Host 'ROOT-ZONE SOIL MOISTURE | Separate research model' -ForegroundColor Green
Write-Host 'Target: water in the top metre of soil, one through fourteen days ahead.'
Write-Host 'This model is separate from the overall drought assessment.'
Write-Host 'CPC legacy tables have been deleted and are not used.'
$rootZonePath = Join-Path $PSScriptRoot 'outputs/root-zone/latest.json'
if (Test-Path -LiteralPath $rootZonePath) {
    $rz = Get-Content -LiteralPath $rootZonePath -Raw | ConvertFrom-Json
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'outputs/root-zone/live/latest.json')) {
        Write-Host 'Historical model trained and sealed; live inputs are connected (see below).' -ForegroundColor Yellow
    } else { Write-Host $rz.status -ForegroundColor Yellow }
    Write-Host ('Historical coverage: {0} watersheds with Connecticut outlets, {1} through {2}.' -f $rz.watersheds,$rz.first_data_date,$rz.last_data_date)
    Write-Host 'These are watershed averages, not readings beneath individual farms.'
    $scorePath = Join-Path $PSScriptRoot ('outputs/root-zone/' + $rz.run + '/scoreboard.json')
    if (Test-Path -LiteralPath $scorePath) {
        $score = Get-Content -LiteralPath $scorePath -Raw | ConvertFrom-Json
        Write-Host 'Historical test: later years held out of training and model selection.'
        foreach ($h in @('1','7','14')) {
            $s = $score.by_horizon.$h
            if ($null -ne $s) {
                Write-Host ('Day {0}: average error {1:N2} soil-water percentage points; unchanged-moisture comparison {2:N2}.' -f $h,($s.mae*100),($s.persistence_mae*100))
                Write-Host ('  {0} target dates; {1} missing comparison values.' -f $s.completed_target_dates,$s.missing_targets)
            }
        }
        Write-Host 'These comparisons use modeled historical soil moisture, not independent sensor measurements.'
    }
} else { Write-Host 'Historical preparation or training is not complete. No live forecast is available.' -ForegroundColor Yellow }
$livePath = Join-Path $PSScriptRoot 'outputs/root-zone/live/latest.json'
if (Test-Path -LiteralPath $livePath) {
    $live = Get-Content -LiteralPath $livePath -Raw | ConvertFrom-Json
    Write-Host ''
    Write-Host ('LIVE RESEARCH FORECAST issued {0} for {1} watersheds' -f $live.issue_date,$live.watersheds_forecast) -ForegroundColor Green
    Write-Host ('Inputs: NASA NLDAS-2 daily moisture {0} through {1} (six-day delay, same as the historical test).' -f $live.input_window[0],$live.input_window[1])
    foreach ($h in @('1','7','14')) {
        $s = $live.summary_by_horizon.$h
        if ($null -ne $s) {
            Write-Host ('Day {0}: median {1:N1}% soil water (range {2:N1}% to {3:N1}% across watersheds).' -f $h,($s.median*100),($s.minimum*100),($s.maximum*100))
        }
    }
    if ($null -ne $live.archive_check) {
        Write-Host ('Input rebuild check vs training archive: average difference {0:N2} percentage points.' -f ($live.archive_check.mae*100))
    }
    Write-Host ('Full table: outputs/root-zone/live/{0}/forecast.csv' -f $live.run)
} else {
    Write-Host 'No live forecast yet. Double-click Refresh Soil Moisture.cmd to assemble recent NASA inputs and issue one.' -ForegroundColor Yellow
}
Write-Host 'Still needed: NASA SMAP comparison and farm sensors.'
Write-Host 'No farm-specific accuracy or overall drought prediction is claimed.'
