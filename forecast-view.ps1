$forecastRoot = Join-Path $PSScriptRoot 'outputs/forecasts'
if (-not (Test-Path -LiteralPath (Join-Path $forecastRoot 'precipitation/summary.json'))) { Write-Host 'Experimental forecasts have not been generated yet.'; return }
$rainForecast = Get-Content -LiteralPath (Join-Path $forecastRoot 'precipitation/summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$wellForecast = Get-Content -LiteralPath (Join-Path $forecastRoot 'groundwater/summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$riverForecast = Get-Content -LiteralPath (Join-Path $forecastRoot 'streamflow/summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Show-FarmForecast($farm) {
    Write-Host ''
    Write-Host $farm.name -ForegroundColor Green
    Write-Host 'PRECIPITATION - experimental past-rainfall baseline'
    if ($farm.status -eq 'experimental') {
        Write-Host ('Expected 14-day amount: {0:N2} inches ({1:N1} mm)' -f $farm.total_14_day_inches, $farm.total_14_day_mm)
        Write-Host ('The model spreads this as {0:N2} inches/day. It does not predict storm dates.' -f ($farm.total_14_day_inches / 14))
        Write-Host ('Held-out test: predicted {0:N2} inches; observed {1:N2} inches; error {2:N2} inches.' -f ($farm.heldout_14_day_prediction_mm / 25.4), ($farm.heldout_14_day_observed_mm / 25.4), ($farm.heldout_14_day_absolute_error_mm / 25.4))
    } else { Write-Host 'Unavailable: missing precipitation data.' }
    Write-Host 'No calibrated uncertainty range. Shared grid cells are not independent farm measurements.'
    Write-Host ''
    Write-Host 'GROUNDWATER BENEATH THIS FARM - unavailable' -ForegroundColor Yellow
    Write-Host 'No confirmed farm well or validated connection to a monitored aquifer.'
    Write-Host 'Nearby well projections are available separately as monitoring context only.'
}
function Show-LocationForecast($record) {
    Write-Host ''
    Write-Host ($record.name + ' | ' + $record.id) -ForegroundColor Green
    Write-Host ('Units: ' + $record.units)
    if ($record.status -ne 'experimental') { Write-Host $record.reason; return }
    $methodNames = @{ persistence = 'Hold the last observed level'; damped_trend = 'Continue the recent trend, with its effect fading'; autoregression = 'Project the pattern in this location''s own past readings' }
    Write-Host ('Method: ' + $methodNames[$record.method])
    Write-Host ('Held-out daily error: {0:N2}; hold-last-reading baseline error: {1:N2} (same units).' -f $record.heldout.mae, $record.heldout.persistence_mae)
    Write-Host ('Beat the simple baseline in the one held-out fortnight: ' + $record.heldout.beats_persistence)
    Write-Host 'Only one test fortnight; no calibrated prediction interval. This is not a validated operational forecast.' -ForegroundColor Yellow
    for ($i = 0; $i -lt 14; $i++) { Write-Host ('  {0}: {1:N2}' -f $record.forecast_dates[$i], $record.daily_prediction[$i]) }
    if ($record.variable -eq 'groundwater') { Write-Host 'A greater depth below ground means a LOWER water level. These values apply only at this monitored well.' }
    else { Write-Host 'These values apply at this gauge, not to every reach, lake, or pond. Farm water access is unknown.' }
}
function Choose-Forecast($items, $kind) {
    $offset = 0
    while ($items.Count -gt 0) {
        $last = [Math]::Min($offset + 12, $items.Count)
        for ($i = $offset; $i -lt $last; $i++) { Write-Host ('  {0}. {1}' -f ($i + 1), $items[$i].name) }
        $selection = Read-Host 'Number for details, N/P for pages, or Enter to return'
        if (-not $selection) { return }
        if ($selection -eq 'n') { if ($last -lt $items.Count) { $offset += 12 }; continue }
        if ($selection -eq 'p') { $offset = [Math]::Max(0,$offset - 12); continue }
        $number = 0
        if ([int]::TryParse($selection,[ref]$number) -and $number -ge 1 -and $number -le $items.Count) {
            if ($kind -eq 'farm') { Show-FarmForecast $items[$number - 1] } else { Show-LocationForecast $items[$number - 1] }
        } else { Write-Host 'Choose a listed number.' }
    }
}
Write-Host 'THREE SEPARATE 14-DAY FORECAST EXPERIMENTS' -ForegroundColor Cyan
Write-Host ('Target dates: {0} through {1}. Source observations stop at {2}.' -f $rainForecast.forecast_dates[0], $rainForecast.forecast_dates[-1], $rainForecast.source_cutoff)
Write-Host 'RESEARCH ONLY: accuracy is not established for farm decisions.' -ForegroundColor Yellow
Write-Host 'Each model uses only its own variable. No drought, crop, or irrigation predictions are added.'
Write-Host 'Rainfall: all mapped farm candidates receive an expected-amount baseline.'
Write-Host 'The rainfall model failed its held-out comparison. It cannot anticipate incoming storms.' -ForegroundColor Yellow
Write-Host ('Groundwater: {0} monitored wells; farm groundwater levels remain unavailable.' -f $wellForecast.forecast_locations)
Write-Host ('Streamflow: {0} gauges; unmonitored waters are not predicted.' -f $riverForecast.forecast_locations)
Write-Host 'Forecasts are a saved experiment, not an automatically updated service.'
Show-FarmForecast $rainForecast.yale
Write-Activity 'Opened separate experimental forecasts. Rainfall benchmark failure and unsupported farm groundwater/waterbody coverage are shown.'
while ($true) {
    Write-Host ''
    $choice = Read-Host 'F = farm by town, G = monitored groundwater wells, S = stream gauges, Enter = return'
    if (-not $choice) { break }
    if ($choice -eq 'f') {
        $townName = Read-Host 'Connecticut town'
        $towns = Get-Content -LiteralPath (Join-Path $forecastRoot 'precipitation/town-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $town = @($towns | Where-Object { $_ -eq $townName.Trim() })
        if ($town.Count -ne 1) { Write-Host 'No mapped farm candidates for that town.'; continue }
        $items = Get-Content -LiteralPath (Join-Path $forecastRoot ('precipitation/towns/' + $town[0] + '.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
        Choose-Forecast @($items) 'farm'
    } elseif ($choice -eq 'g' -or $choice -eq 's') {
        $kind = if ($choice -eq 'g') { 'groundwater' } else { 'streamflow' }
        $items = Get-Content -LiteralPath (Join-Path $forecastRoot ($kind + '/location-forecasts.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
        $supported = @($items | Where-Object { $_.status -eq 'experimental' } | Sort-Object name)
        Choose-Forecast $supported $kind
    } else { Write-Host 'Choose F, G, S, or Enter.' }
}
