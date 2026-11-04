$Host.UI.RawUI.WindowTitle = 'Ahead of the Storm | Behind the Scenes'
$activityPath = Join-Path $PSScriptRoot 'activity.log'
Clear-Host
Write-Host 'AHEAD OF THE STORM' -ForegroundColor Cyan
Write-Host 'Behind the Scenes | What the app is doing'
Write-Host ''
Write-Host 'RESEARCH VERSION - Separate forecast experiments; not operationally validated.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Ready: Farmer menu and activity display'
$statewidePath = Join-Path $PSScriptRoot 'outputs/statewide/summary.json'
if (Test-Path -LiteralPath $statewidePath) {
    $statewide = Get-Content -LiteralPath $statewidePath -Raw | ConvertFrom-Json
    Write-Host ('Ready: Statewide inventory - {0} towns and {1:N0} candidates' -f $statewide.towns_processed, $statewide.candidate_records)
    Write-Host 'Needs review: Public outlines are not confirmed farm operating boundaries'
}
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data/yale-farm/profile.json')) {
    Write-Host 'Ready: Yale Farm parcel comparison, aerial photo, and satellite image'
    Write-Host 'Needs review: Farm extent differs from the published approximate acreage'
    Write-Host 'Waiting: Confirmed growing areas, crops, irrigation resources, and sensors'
}
$catalogPath = Join-Path $PSScriptRoot 'data/watershed-catalog.json'
if (Test-Path -LiteralPath $catalogPath) {
    $catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
    Write-Host ('Ready: CT DEEP watershed boundaries - 8 major areas, {0} smaller watershed IDs' -f $catalog.watershed_count)
    Write-Host 'Separate pieces with the same watershed number are grouped together.'
    Write-Host 'Cross-border portions are retained. Drought risk is not calculated yet.'
}
$rainPath = Join-Path $PSScriptRoot 'outputs/precipitation/summary.json'
if (Test-Path -LiteralPath $rainPath) {
    $rain = Get-Content -LiteralPath $rainPath -Raw | ConvertFrom-Json
    Write-Host ('Ready: PRISM daily precipitation through {0}; snapshot {1}' -f $rain.end, $rain.snapshot)
    Write-Host 'Totals: Past 7, 14, 30, 60, and 90 days. Recent values may be revised.'
    Write-Host 'Missing data stays missing. No automatic refresh is running.'
} else { Write-Host 'Preparing: PRISM daily precipitation. Follow progress below.' }
Write-Host 'Waiting: Farm details, soil datasets, and sensor connections'
$groundPath = Join-Path $PSScriptRoot 'outputs/groundwater/summary.json'
if (Test-Path -LiteralPath $groundPath) {
    $ground = Get-Content -LiteralPath $groundPath -Raw | ConvertFrom-Json
    Write-Host ('Ready: USGS groundwater - {0} wells with readings in the saved 90-day window' -f $ground.wells_with_recent_readings)
    Write-Host ('Coverage gap: {0} towns have no recent reading in these sources' -f $ground.towns_without_recent_well)
    Write-Host 'Nearby wells are context, not farm measurements. No automatic refresh is running.'
}
Write-Host 'Waiting: Climate research and local resource information'
$flowPath = Join-Path $PSScriptRoot 'outputs/streamflow/summary.json'
if (Test-Path -LiteralPath $flowPath) {
    $flow = Get-Content -LiteralPath $flowPath -Raw | ConvertFrom-Json
    Write-Host ('Ready: USGS streamflow - {0} recent gauges; {1} with historical percentile thresholds' -f $flow.recent_gauges, $flow.recent_series_with_percentile_context)
    Write-Host 'Missing days stay missing; river connectivity and farm water access are not established.'
}
Write-Host 'Available: Separate precipitation, well-level, and gauged-stream forecast experiments'
Write-Host 'Test result: Rainfall baseline missed the held-out dry spell; see option 1'
Write-Host 'Waiting: Reliable forecast validation and farm/waterbody monitoring connections'
Write-Host ''
Write-Host 'Actual activity appears below as you use the Farmer View.'
Write-Host 'Recent entries are saved locally in activity.log. Each entry indicates its time zone.'
Write-Host 'Close this window when you are finished.'
Write-Host ''
if (-not (Test-Path -LiteralPath $activityPath)) {
    New-Item -ItemType File -Path $activityPath | Out-Null
}
Get-Content -LiteralPath $activityPath -Tail 15 -Wait
