Write-Host 'COASTAL WATER TEMPERATURE | Long Island Sound and Connecticut coast, next 14 days' -ForegroundColor Green
Write-Host 'Daily average water temperature at NOAA buoys and coastal stations (National Data Buoy Center).'
$root = $PSScriptRoot
$names = @{}
$man = Join-Path $root 'data/water-temp/manifest.json'
if (Test-Path -LiteralPath $man) { (Get-Content -LiteralPath $man -Raw -Encoding UTF8 | ConvertFrom-Json).stations.PSObject.Properties | ForEach-Object { $names[$_.Name] = $_.Value.name } }
$runPath = Join-Path $root 'outputs/water-temp-prospective/last-run.json'
if (Test-Path -LiteralPath $runPath) {
    $run = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($run.sealed_today) {
        $issue = Get-Content -LiteralPath (Join-Path $root $run.sealed_today) -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ('Forecast issued {0} UTC, sealed before these days began. Degrees F (C).' -f $issue.issued_at) -ForegroundColor Cyan
        Write-Host ('{0,-46} {1,-14} {2,-14} {3,-14}' -f 'Station', 'Yesterday', 'Day 7', 'Day 14')
        foreach ($f in $issue.forecasts) {
            $fmt = { param($c) '{0:N1} F ({1:N1})' -f ($c * 1.8 + 32), $c }
            Write-Host ('{0,-46} {1,-14} {2,-14} {3,-14}' -f $names[$f.id], (& $fmt $f.baseline[0]), (& $fmt $f.prediction[6]), (& $fmt $f.prediction[13]))
        }
        foreach ($m in $issue.unavailable) { Write-Host ('{0}: no forecast today ({1})' -f $names[$m.id], $m.reason) -ForegroundColor Yellow }
    } else { Write-Host 'No forecast sealed today yet.' -ForegroundColor Yellow }
}
$test = Join-Path $root 'outputs/water-temp/latest.json'
if (Test-Path -LiteralPath $test) {
    $t = Get-Content -LiteralPath $test -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ''
    Write-Host 'Tested on 2022-2025, kept out of training (average error, degrees C):'
    foreach ($h in @('1','7','14')) {
        $s = $t.by_forecast_day.$h
        if ($s) { Write-Host ('  Day {0}: {1:N2} vs {2:N2} if unchanged, {3:N2} for the seasonal normal; 90% range held {4:P0}' -f $h, $s.mae_c, $s.persistence_mae_c, $s.normal_mae_c, $s.band_coverage) }
    }
}
Write-Host ''
Write-Host 'Uses only past water temperature (no weather forecast), so it cannot foresee a sudden storm or upwelling.' -ForegroundColor Yellow
Write-Host 'Readings are at each buoy or pier, not in every cove or farm pond. Daily tests: Farmer View option 11.'
