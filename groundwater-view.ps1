$folder = Join-Path $PSScriptRoot 'outputs/groundwater'
if (-not (Test-Path -LiteralPath (Join-Path $folder 'summary.json'))) { Write-Host 'Groundwater data is not loaded yet.'; return }
$ground = Get-Content -LiteralPath (Join-Path $folder 'summary.json') -Raw | ConvertFrom-Json
$wells = Get-Content -LiteralPath (Join-Path $folder 'wells.json') -Raw | ConvertFrom-Json
$coverage = Get-Content -LiteralPath (Join-Path $folder 'town-coverage.json') -Raw | ConvertFrom-Json
function Show-Well($well) {
    Write-Host ''
    Write-Host ($well.name + ' | ' + $well.id) -ForegroundColor Green
    Write-Host ('Town: ' + ($well.towns -join ', ') + ' | Surface watershed: ' + ($well.watershed_ids -join ', '))
    if ($null -eq $well.latest) { Write-Host 'No usable water-level reading in the queried window.'; return }
    $reading = $well.latest
    Write-Host ('Latest imported: {0} | {1} days before snapshot | {2}' -f $reading.date, $well.age_days, $reading.type)
    if ($reading.depth_below_land_ft -ge 0) { Write-Host ('Water level: {0:N2} feet below ground at THIS WELL' -f $reading.depth_below_land_ft) }
    else { Write-Host ('Water level: {0:N2} feet above the land-surface reference at THIS WELL' -f (-$reading.depth_below_land_ft)) }
    Write-Host ('USGS status: {0}' -f $reading.approval_status)
    Write-Host ('Past 90 days: {0} days with daily means; {1} manual visit dates' -f $well.daily_days, $well.manual_visits)
    Write-Host ('Aquifer code: {0}; connection to your farm has not been established.' -f $well.aquifer_code)
    Write-Host 'A larger depth below ground means a LOWER water level. Depths at different wells are not directly comparable.'
    Write-Host $well.url
}
Write-Host 'GROUNDWATER MONITORING' -ForegroundColor Cyan
Write-Host ('Saved snapshot: {0}. Observations searched: {1} through {2}.' -f $ground.snapshot, $ground.window_start, $ground.window_end)
Write-Host ('{0:N0} listed well locations; {1} wells have usable readings in this 90-day window.' -f $ground.listed_wells, $ground.wells_with_recent_readings)
Write-Host ('{0} towns have no recent well reading in these imported sources.' -f $ground.towns_without_recent_well)
Write-Host 'Source: USGS Water Data. The separate NGWMN download service returned an error.'
Write-Host 'No groundwater levels are estimated for unmonitored farms.' -ForegroundColor Yellow
Write-Host 'Nearby does not mean the same aquifer. Surface watersheds do not prove groundwater connection.'
Write-Host ''
Write-Host 'Yale Farm: three closest wells with readings in this window'
foreach ($link in $ground.yale_nearby_wells) {
    Write-Host ('Distance from farm reference point: {0:N1} km ({1:N1} miles)' -f $link.distance_km, ($link.distance_km / 1.609344))
    $well = $wells | Where-Object { $_.id -eq $link.well_id } | Select-Object -First 1
    Show-Well $well
}
Write-Activity 'Viewed groundwater observations and coverage gaps. No farm groundwater level or recommendation was inferred.'
while ($true) {
    Write-Host ''
    $answer = Read-Host 'Enter a town or full USGS well ID, or Enter to return'
    if (-not $answer) { break }
    if ($answer -like 'USGS-*') {
        $well = $wells | Where-Object { $_.id -eq $answer.Trim() } | Select-Object -First 1
        if ($well) { Show-Well $well } else { Write-Host 'Well ID not found.' }
        continue
    }
    $town = $coverage | Where-Object { $_.town -eq $answer.Trim() } | Select-Object -First 1
    if (-not $town) { Write-Host 'Town not found.'; continue }
    Write-Host ('{0}: {1} listed wells; {2} with readings in this window.' -f $town.town, $town.listed_wells, $town.wells_with_recent_readings)
    if ($town.wells_with_recent_readings -eq 0) { Write-Host 'Coverage gap. This does not mean groundwater is absent or that wells are dry.' }
    foreach ($id in $town.recent_well_ids) { Show-Well ($wells | Where-Object { $_.id -eq $id } | Select-Object -First 1) }
}
