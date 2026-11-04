$path = Join-Path $PSScriptRoot 'outputs/precipitation/summary.json'
if (-not (Test-Path -LiteralPath $path)) {
    Write-Host 'Daily rainfall grids are being prepared. Follow Behind the Scenes for progress.'
    return
}
$rain = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
$livePointerPath = Join-Path $PSScriptRoot 'outputs/forecasts/precipitation/noaa-live/latest.json'
$liveById = @{}
$live = $null
if (Test-Path -LiteralPath $livePointerPath) {
    $pointer = Get-Content -LiteralPath $livePointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $livePath = Join-Path $PSScriptRoot $pointer.path
    $live = Get-Content -LiteralPath $livePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $live.forecasts) { $liveById[$item.id] = $item }
}
function Show-Rainfall($record) {
    Write-Host ''
    Write-Host $record.name -ForegroundColor Green
    if ($record.parcel_addresses) { Write-Host ('Nearby/overlapping property addresses: ' + ($record.parcel_addresses -join '; ')) }
    if ($record.watershed_ids) { Write-Host ('Watershed numbers: ' + ($record.watershed_ids -join ', ')) }
    Write-Host ('Mapped grid cells used: {0}' -f $record.grid_cells)
    Write-Host $record.method
    if ($live -and $liveById.ContainsKey($record.id)) {
        $forecast = $liveById[$record.id]
        Write-Host ('LIVE PRECIPITATION OUTLOOK - issued {0}; NOAA NBM cycle {1}' -f $live.issued_at,$live.cycle) -ForegroundColor Cyan
        Write-Host 'Forecast days are local calendar days. NOAA amounts are model guidance; final days use the labeled historical blend.'
        for ($i = 0; $i -lt $live.forecast_dates.Count; $i++) {
            $mm = $forecast.daily_precipitation_mm[$i]
            $source = $forecast.day_sources[$i]
            if ($null -eq $mm) { Write-Host ('  {0}: unavailable' -f $live.forecast_dates[$i]) }
            else { Write-Host ('  {0}: {1:N2} inches | {2}' -f $live.forecast_dates[$i],($mm / 25.4),$source) }
        }
        Write-Host 'Candidate parcel location only; farm boundary is not confirmed. Forecast ranges are not calibrated.' -ForegroundColor Yellow
    } else { Write-Host 'Live NOAA forecast is not available for this mapped location.' -ForegroundColor Yellow }
    foreach ($days in $rain.windows) {
        $value = $record.totals.PSObject.Properties[[string]$days].Value
        if ($null -eq $value.mm) {
            Write-Host ('  Past {0} days: Missing data; no complete total' -f $days)
        } else {
            Write-Host ('  Past {0,2} days: {1,6:N2} inches ({2:N1} mm)' -f $days, $value.inches, $value.mm)
        }
    }
}
Write-Host 'CUMULATIVE PRECIPITATION' -ForegroundColor Cyan
Write-Host ('Daily records through {0}, ending at 12:00 UTC on that date.' -f $rain.end)
Write-Host ('Downloaded snapshot: {0}. Recent PRISM estimates may be revised.' -f $rain.snapshot)
Write-Host 'Includes rain and the water equivalent of snow. Missing readings never count as zero.'
Write-Host 'Past estimates and live precipitation forecasts are shown separately; no drought rating is produced.' -ForegroundColor Yellow
Write-Host 'Nominal 800-meter grids can cover multiple farms; boundaries still need review.'
Show-Rainfall $rain.yale
Write-Host ''
Write-Host $rain.attribution
Write-Activity ('Viewed precipitation through ' + $rain.end + '. No drought rating or recommendation produced.')
while ($true) {
    Write-Host ''
    $lookup = Read-Host 'Enter a town, a watershed number (such as 5302), or Enter to return'
    if (-not $lookup) { break }
    $watershed = 0
    if ([int]::TryParse($lookup, [ref]$watershed)) {
        $allWatersheds = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'outputs/precipitation/watersheds.json') -Raw | ConvertFrom-Json
        $items = @($allWatersheds | Where-Object { $_.watershed_id -eq $lookup })
        if ($items.Count) { Write-Host 'Connecticut portion of this watershed only.'; Show-Rainfall $items[0] }
        else { Write-Host 'Watershed number not found.' }
        continue
    }
    $towns = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'outputs/precipitation/town-index.json') -Raw | ConvertFrom-Json
    $town = @($towns | Where-Object { $_ -eq $lookup.Trim() })
    if ($town.Count -ne 1) { Write-Host 'No mapped candidates for that town in this dataset.'; continue }
    $townItems = Get-Content -LiteralPath (Join-Path $PSScriptRoot ('outputs/precipitation/towns/' + $town[0] + '.json')) -Raw | ConvertFrom-Json
    $items = @($townItems)
    $offset = 0
    while ($true) {
        $last = [Math]::Min($offset + 12, $items.Count)
        for ($i = $offset; $i -lt $last; $i++) { Write-Host ('  {0}. {1}' -f ($i + 1), $items[$i].name) }
        $answer = Read-Host 'Choose a number, N for next, P for previous, or Enter to finish this town'
        if (-not $answer) { break }
        if ($answer -eq 'n') { if ($last -lt $items.Count) { $offset += 12 }; continue }
        if ($answer -eq 'p') { $offset = [Math]::Max(0, $offset - 12); continue }
        $number = 0
        if ([int]::TryParse($answer,[ref]$number) -and $number -ge 1 -and $number -le $items.Count) { Show-Rainfall $items[$number - 1] }
        else { Write-Host 'Choose a number from the list.' }
    }
}
