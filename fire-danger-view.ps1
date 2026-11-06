Write-Host 'FOREST FIRE DANGER | Connecticut statewide, next 14 days' -ForegroundColor Green
Write-Host 'Classes: LOW, MODERATE, HIGH, VERY HIGH, EXTREME (Connecticut DEEP Division of Forestry scale).'
$root = $PSScriptRoot
$deepPath = Join-Path $root 'data/fire-danger/deep-ratings.json'
if (Test-Path -LiteralPath $deepPath) {
    $deep = Get-Content -LiteralPath $deepPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $last = $deep.ratings.PSObject.Properties | Sort-Object Name | Select-Object -Last 1
    if ($last) { Write-Host ('Latest official DEEP rating: {0} for {1}. {2}' -f $last.Value.level, $last.Name, $last.Value.note) -ForegroundColor Yellow }
}
$runPath = Join-Path $root 'outputs/fire-danger-prospective/last-run.json'
if (Test-Path -LiteralPath $runPath) {
    $run = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($run.sealed_today) {
        $issue = Get-Content -LiteralPath (Join-Path $root $run.sealed_today) -Raw -Encoding UTF8 | ConvertFrom-Json
        $f = $issue.forecasts[0]
        Write-Host ''
        Write-Host ('Forecast issued {0} UTC (sealed before these days began):' -f $issue.issued_at) -ForegroundColor Cyan
        Write-Host 'Date         Class       Spread  Build Up  Source'
        for ($i = 0; $i -lt $f.dates.Count; $i++) {
            $src = if ($f.methods[$i] -like 'NOAA*') { 'NOAA weather forecast' } else { 'past patterns (climatology)' }
            Write-Host ('{0}   {1,-10} {2,6} {3,9}  {4}' -f $f.dates[$i], $f.levels[$i], $f.spread_index[$i], $f.buildup_index[$i], $src)
        }
    } else { Write-Host 'No forecast sealed today yet. Latest problems are in outputs/fire-danger-prospective/last-run.json.' -ForegroundColor Yellow }
}
$val = Join-Path $root 'data/fire-danger/validation.json'
if (Test-Path -LiteralPath $val) {
    $v = Get-Content -LiteralPath $val -Raw -Encoding UTF8 | ConvertFrom-Json
    $r = $v.results.'timber/median/buildup'
    Write-Host ''
    Write-Host ('How well the rebuilt method matches DEEP: same class on {0:P0} of {1} published DEEP ratings, within one class on {2:P0}.' -f $r.exact, $r.dates, $r.within_one)
}
$test = Join-Path $root 'outputs/fire-danger/latest-test.json'
if (Test-Path -LiteralPath $test) {
    $t = Get-Content -LiteralPath $test -Raw -Encoding UTF8 | ConvertFrom-Json
    $d14 = $t.by_horizon.'14'
    Write-Host ('Past-pattern days (after NOAA weather runs out), tested on 2019-2025: day-14 class right {0:P0} vs {1:P0} for "no change".' -f $d14.accuracy, $d14.persistence_accuracy)
}
Write-Host ''
Write-Host 'How it works: DEEP rates fire danger from a Spread Index (wind, humidity) and a Build Up Index (drying since rain).'
Write-Host 'This model recalculates them with the 1964 national method from airport weather and NOAA forecasts.'
Write-Host 'Statewide only; not a burn permit decision. Always check DEEP''s official rating and local rules before burning.' -ForegroundColor Yellow
