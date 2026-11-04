$flowFolder = Join-Path $PSScriptRoot 'outputs/streamflow'
if (-not (Test-Path -LiteralPath (Join-Path $flowFolder 'summary.json'))) { Write-Host 'Streamflow is not loaded yet.'; return }
$flowSummary = Get-Content -LiteralPath (Join-Path $flowFolder 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$gauges = Get-Content -LiteralPath (Join-Path $flowFolder 'gauges.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Show-Streamflow($gauge) {
    Write-Host ''
    Write-Host ($gauge.name + ' | ' + $gauge.gauge_id) -ForegroundColor Green
    Write-Host ('Town: ' + ($gauge.towns -join ', ') + ' | Surface watershed: ' + ($gauge.watershed_ids -join ', '))
    if (-not $gauge.latest) { Write-Host 'No usable daily mean was returned for this series.'; return }
    Write-Host ('Latest imported daily average: {0:N2} cubic feet per second on {1}' -f $gauge.latest.flow_cfs, $gauge.latest.date)
    Write-Host ('Age at snapshot: {0} days | USGS status: {1}' -f $gauge.age_days, $gauge.latest.approval_status)
    if ($gauge.latest.qualifier) { Write-Host ('Quality notes: ' + ($gauge.latest.qualifier -join ', ')) }
    foreach ($days in @(7,14,30,90)) {
        $average = $gauge.averages.PSObject.Properties[[string]$days].Value
        if ($null -eq $average.mean_cfs) { Write-Host ('Past {0} days: average withheld; {1}/{0} days available' -f $days, $average.available_days) }
        else { Write-Host ('Past {0} days: average {1:N2} cubic feet per second; {2} days have quality notes' -f $days, $average.mean_cfs, $average.qualified_days) }
    }
    if ($gauge.seasonal_context) {
        $context = $gauge.seasonal_context
        Write-Host ('Latest day compared with this gauge''s historical seasonal values: ' + $context.band)
        Write-Host ('Historical median for {0}: {1:N2} cubic feet per second; {2} approved historical samples' -f $context.month_day, $context.thresholds_cfs.'50', $context.sample_count)
        Write-Host 'This is a percentile BAND, not an exact percentile or a farm drought rating.'
    } else { Write-Host 'Historical percentile comparison unavailable. No substitute percentile is assigned.' }
    Write-Host 'Reservoir operations and withdrawals can affect flow. Water access and river connection to your farm are unverified.'
    Write-Host $gauge.url
}
Write-Host 'STREAMFLOW AND SEASONAL CONTEXT' -ForegroundColor Cyan
Write-Host ('Saved through {0} | Snapshot {1} | {2} gauges with recent daily records' -f $flowSummary.end, $flowSummary.snapshot, $flowSummary.recent_gauges)
Write-Host ('Official historical percentile thresholds available for {0} recent series.' -f $flowSummary.recent_series_with_percentile_context)
Write-Host 'Discharge means the volume of water passing the gauge each second.'
Write-Host 'Daily averages are not instantaneous readings. Missing days never count as zero.'
Write-Host 'No two-week forecast, farm water allocation, or irrigation recommendation is produced.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Yale Farm: nearby gauges for context'
foreach ($link in $flowSummary.yale_nearby_gauges) {
    Write-Host ('Distance: {0:N1} miles | Same mapped surface watershed: {1}' -f ($link.distance_km / 1.609344), $link.same_surface_watershed)
    Write-Host 'Upstream/downstream connection to the farm: not established'
    Show-Streamflow ($gauges | Where-Object { $_.series_id -eq $link.series_id } | Select-Object -First 1)
}
Write-Activity 'Viewed USGS daily streamflow and official seasonal percentile thresholds. No farm water supply was inferred.'
while ($true) {
    Write-Host ''
    $answer = Read-Host 'Enter a town, watershed number, or full USGS gauge ID; Enter to return'
    if (-not $answer) { break }
    $basinNumber = 0
    if ($answer -like 'USGS-*') { $matches = @($gauges | Where-Object { $_.gauge_id -eq $answer.Trim() }) }
    elseif ([int]::TryParse($answer,[ref]$basinNumber)) { $matches = @($gauges | Where-Object { $_.days_observed -gt 0 -and $_.watershed_ids -contains $answer.Trim() }) }
    else { $matches = @($gauges | Where-Object { $_.days_observed -gt 0 -and $_.towns -contains $answer.Trim() }) }
    if (-not $matches.Count) { Write-Host 'No matching gauge with imported data. This is a monitoring gap, not zero flow.' }
    foreach ($gauge in $matches) { Show-Streamflow $gauge }
}
