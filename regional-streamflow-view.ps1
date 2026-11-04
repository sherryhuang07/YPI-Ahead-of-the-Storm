$root = Join-Path $PSScriptRoot 'outputs/regional-streamflow'
$summary = Get-Content (Join-Path $root 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$bodies = Get-Content (Join-Path $root 'water-feature-context.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$gauges = Get-Content (Join-Path $root 'relevant-gauges.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$lookup = @{}; foreach ($g in $gauges) { $lookup[$g.gauge_id] = $g }
$predictions = @{}; $latestPath = Join-Path $PSScriptRoot 'outputs/regional-prospective/scoreboard.json'
if (Test-Path $latestPath) {
    $score = Get-Content $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $latest = $score.issues | Sort-Object issued_at | Select-Object -Last 1
    if ($latest) {
        $files = Get-ChildItem (Join-Path $PSScriptRoot "outputs/regional-prospective/issued/$($latest.day)") -Filter '*.json' | Sort-Object Name
        foreach ($file in $files) {
            $issue = Get-Content $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($issue.issued_at -eq $latest.issued_at) {
                foreach ($p in $issue.forecasts) { $predictions[$p.id] = $p }
                Write-Host "Forecast issue (UTC): $($issue.issued_at)"
            }
        }
    }
}
Write-Host 'CONNECTED GAUGES BEYOND CONNECTICUT' -ForegroundColor Cyan
Write-Host "$($summary.relevant_gauges) connected gauges in neighboring states and upper-basin states."
Write-Host 'Each forecast describes flow at that gauge; it is not transferred to a Connecticut location.'
Write-Host 'Upstream tributaries can contribute flow. Downstream gauges provide context, not upstream causes.'
$query = Read-Host 'Enter a river or waterbody name (Enter for Connecticut River)'
if (-not $query) { $query = 'Connecticut River' }
$matches = @($bodies | Where-Object { $_.name -like "*$query*" -and $_.kind -ne 'unnamed_reach' })
if (-not $matches.Count) { Write-Host 'No matching named feature. Unnamed mapped features are retained in the data inventory.'; return }
foreach ($body in $matches) {
    Write-Host "`n$($body.name) [$($body.source_id)]" -ForegroundColor Green
    if (-not $body.outside_gauges.Count) { Write-Host $body.coverage; continue }
    foreach ($link in $body.outside_gauges) {
        $g = $lookup[$link.gauge_id]
        Write-Host "$($g.name) - $($g.gauge_id)"
        Write-Host "  $($g.state): $($link.relationships -join '; ')"
        if ($link.same_named_waterway) { Write-Host '  On the same named waterway.' }
        if ($g.association_method -like 'Coordinate*') { Write-Host '  Connection uses a catchment, matching name and stream-distance check; needs field review.' }
        if ($predictions.ContainsKey($g.gauge_id)) {
            $p = $predictions[$g.gauge_id]
            Write-Host ('  {0}: {1:N1} -> {2}: {3:N1} cubic feet/second; last input {4}.' -f $p.dates[0],$p.prediction[0],$p.dates[-1],$p.prediction[-1],$p.source_last_day)
        } else { Write-Host '  No current validated-input 14-day forecast; gauge remains listed as context.' }
    }
}
Write-Host "`nRiver travel time, dams and tidal changes are not simulated. Extra context does not yet prove lower Connecticut forecast error."
