Write-Host 'DROUGHT FORECAST | U.S. Drought Monitor class, next two weekly maps' -ForegroundColor Green
Write-Host 'Combines every model in this app: rain, streams, wells, soil moisture, fire build-up, coastal water,'
Write-Host 'plus the Palmer Drought Index and the current Drought Monitor map.'
Write-Host 'Classes: None, D0 abnormally dry, D1 moderate, D2 severe, D3 extreme, D4 exceptional drought.'
$root = $PSScriptRoot
$runPath = Join-Path $root 'outputs/drought-prospective/last-run.json'
$farms = $null
$fr = Join-Path $root 'data/drought/farm-regions.json'
if (Test-Path -LiteralPath $fr) { $farms = (Get-Content -LiteralPath $fr -Raw -Encoding UTF8 | ConvertFrom-Json).by_region }
if (Test-Path -LiteralPath $runPath) {
    $run = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($run.sealed_today) {
        $issue = Get-Content -LiteralPath (Join-Path $root $run.sealed_today) -Raw -Encoding UTF8 | ConvertFrom-Json
        $f0 = $issue.forecasts[0]
        Write-Host ''
        Write-Host ('Issued {0} UTC (sealed before the target maps). Maps valid {1} and {2}.' -f $issue.issued_at, $f0.dates[0], $f0.dates[1]) -ForegroundColor Cyan
        Write-Host ('{0,-48} {1,-9} {2,-16} {3,-16} {4}' -f 'Area', 'Now', $f0.dates[0], $f0.dates[1], 'Farms')
        foreach ($f in ($issue.forecasts | Sort-Object { if ($_.id -eq 'CT') { '0' } else { $_.id } })) {
            $name = if ($f.id -eq 'CT') { 'Connecticut (statewide)' } else { ($f.id -split '\|')[1] }
            $c1 = '{0} ({1:P0} worse)' -f $f.dominant_class[0], $f.chance_worse[0]
            $c2 = '{0} ({1:P0} worse)' -f $f.dominant_class[1], $f.chance_worse[1]
            $n = if ($farms -and $f.id -ne 'CT') { $farms.($f.id) } else { '' }
            Write-Host ('{0,-48} {1,-9} {2,-16} {3,-16} {4}' -f $name, $f.current_class, $c1, $c2, $n)
        }
        Write-Host ('Rain during the forecast weeks: {0}.' -f $f0.rain_ahead_source[1])
        Write-Host '"worse" = chance the class is more severe by that map. The class moves only if a change is more likely than not.'
        $now = $issue.forecasts | Where-Object { $_.id -eq 'CT' }
        if ($now) { Write-Host ('Statewide chance of improving by each map: {0:P0} and {1:P0}.' -f $now.chance_better[0], $now.chance_better[1]) }
        foreach ($m in $issue.unavailable) { Write-Host ('{0}: {1}' -f $m.id, $m.reason) -ForegroundColor Yellow }
    } else { Write-Host 'No drought forecast sealed today yet.' -ForegroundColor Yellow }
}
$test = Join-Path $root 'outputs/drought/latest.json'
if (Test-Path -LiteralPath $test) {
    $t = Get-Content -LiteralPath $test -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ''
    Write-Host 'Tested on 2019-2026, kept out of training (statewide and regions):'
    foreach ($k in @('1','2','3')) {
        $s = $t.by_lead_weeks.$k
        if ($s) {
            $w = $s.probabilities.worsen_normal_rain; $i = $s.probabilities.improve_normal_rain
            Write-Host ('  {0} week(s) ahead: class right {1:P0} (unchanged map {2:P0}). Chance of worsening ranks real worsening weeks above others {3:P0} of the time; improving {4:P0}.' -f $k, $s.probabilities.class_with_step_rule, $s.persistence_cat, $w.auc, $i.auc)
        }
    }
}
$v2Path = Join-Path $root 'outputs/drought-v2-prospective/last-run.json'
if (Test-Path -LiteralPath $v2Path) {
    $v2 = Get-Content -LiteralPath $v2Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($v2.sealed_today) {
        $ct = (Get-Content -LiteralPath (Join-Path $root $v2.sealed_today) -Raw -Encoding UTF8 | ConvertFrom-Json).forecasts | Where-Object { $_.id -eq 'CT' }
        Write-Host ''
        Write-Host 'Version 2 (adds USGS VegDRI satellite plant stress), statewide:' -ForegroundColor Cyan
        if ($ct) { Write-Host ('  {0} -> {1} / {2}; chance worse {3:P0} / {4:P0}' -f $ct.current_class, $ct.dominant_class[0], $ct.dominant_class[1], $ct.chance_worse[0], $ct.chance_worse[1]) }
    }
}
$veg = Join-Path $root 'data/drought/vegdri-weekly.csv'
if (Test-Path -LiteralPath $veg) {
    $last = Import-Csv -LiteralPath $veg | Where-Object { $_.unit -eq 'CT' -and $_.mean -ne '' } | Sort-Object week_end | Select-Object -Last 1
    if ($last) { Write-Host ('Satellite plant stress (VegDRI), week ending {0}: statewide index {1:N2}; {2:N0}% of vegetated land below -1 (stressed).' -f $last.week_end, [double]$last.mean, [double]$last.pct_below_minus1) }
}
Write-Host ''
Write-Host 'Each farm takes its planning region''s forecast; local conditions can differ (Drought Monitor maps are broad-scale).' -ForegroundColor Yellow
Write-Host 'Daily tests and the learning version: Farmer View option 11.'
