$summary = Get-Content (Join-Path $PSScriptRoot 'outputs/streamflow-trained/summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$records = Get-Content (Join-Path $PSScriptRoot 'outputs/streamflow-trained/results.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host 'STREAMFLOW: LEARNING FROM LONGER HISTORIES' -ForegroundColor Cyan
Write-Host "Saved forecast issued $($summary.issued), for November 4-17, 2026."
Write-Host "$($summary.trained_gauges) gauges passed the history requirements; $($summary.requested_gauges) were examined."
Write-Host "$($summary.beat_persistence) beat keeping the latest flow unchanged in the later-year test."
Write-Host 'Inputs: each gauge''s own past flow and the time of year.'
Write-Host 'No future rain, groundwater, dam-release plans or farm sensors are included.'
Write-Host 'These are experimental forecasts at gauges, not predictions for every river or lake.' -ForegroundColor Yellow
Write-Host ''
$search = Read-Host 'Enter part of a river or gauge name (Enter for Mill River near Hamden)'
if (-not $search) { $search = 'MILL RIVER NEAR HAMDEN' }
$matches = @($records | Where-Object { $_.name -like "*$search*" })
foreach ($g in $matches) {
    Write-Host "`n$($g.name) - $($g.gauge_id)" -ForegroundColor Green
    if (-not $g.forecast) { Write-Host $g.status; continue }
    Write-Host ('Average test error: {0:N1} cubic feet per second; unchanged-flow comparison: {1:N1}.' -f $g.metrics.mae_cfs,$g.metrics.persistence_mae_cfs)
    Write-Host ('The nominal 90% daily range covered {0:P0} of later test observations.' -f $g.metrics.interval_coverage)
    Write-Host 'Date       Central estimate     Lower range     Upper range (cubic feet/second)'
    foreach ($day in $g.forecast) { Write-Host ('{0}       {1,9:N1}       {2,9:N1}       {3,9:N1}' -f $day.date,$day.flow_cfs,$day.lower_90_cfs,$day.upper_90_cfs) }
}
if (-not $matches.Count) { Write-Host 'No matching gauge found.' }
$networkPath = Join-Path $PSScriptRoot 'outputs/river-network/summary.json'
if (Test-Path $networkPath) {
    $network = Get-Content $networkPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "`nMapping: $($network.farms_with_hr_catchment) of $($network.farms) candidate fields overlap a mapped catchment."
    Write-Host "$($network.farms_in_monitored_basins) overlap approximate gauge drainage maps."
    Write-Host 'Those basin maps include whole local catchments and can extend below a gauge.'
    Write-Host 'This identifies drainage geography, not a measurement at the farm or permission to use water.'
}
