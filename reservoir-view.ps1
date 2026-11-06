$path = Join-Path $PSScriptRoot 'data/reservoirs/2024-11-12.json'
if (-not (Test-Path -LiteralPath $path)) {
    Write-Host 'The Connecticut DPH reservoir-capacity snapshot is not loaded.' -ForegroundColor Yellow
    return
}

$data = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
$reportDate = [DateTime]::ParseExact($data.report_date,'yyyy-MM-dd',$null)
$ageDays = ((Get-Date).Date - $reportDate.Date).Days

Write-Host 'DRINKING-WATER SYSTEM SURFACE CAPACITY' -ForegroundColor Cyan
Write-Host 'Connecticut DPH report date: ' $reportDate.ToString('MMMM d, yyyy')
Write-Host ('{0} public water systems; reported reading dates range {1} to {2}.' -f $data.report_summary.systems,$data.report_summary.reading_date_min,$data.report_summary.reading_date_max)
Write-Host ('This snapshot is {0:N0} days old. It is not a current operating status.' -f $ageDays) -ForegroundColor Yellow
Write-Host 'Each row describes a water system that may use several reservoirs, not a named reservoir.'
Write-Host 'County served is the system service area; it does not locate the reservoir.'
Write-Host ''
Write-Host ('Table average: {0:N1}% full; {1:N1}% of historical normal.' -f $data.report_summary.table_footer_averages.percent_full,$data.report_summary.table_footer_averages.percent_of_normal)
Write-Host ('Reported short-term trends: {0} up, {1} down, {2} unchanged.' -f $data.report_summary.trend_counts.up,$data.report_summary.trend_counts.down,$data.report_summary.trend_counts.unchanged)
Write-Host ('Report status: {0} at no drought stage, {1} approaching a trigger, {2} at water-supply advisory.' -f $data.report_summary.status_counts.'No Drought Stage',$data.report_summary.status_counts.'Approaching Trigger Level',$data.report_summary.status_counts.'Water Supply Advisory')
Write-Host ''
$historyPath = Join-Path $PSScriptRoot 'data/reservoirs/historical/history-audit.json'
if (Test-Path -LiteralPath $historyPath) {
    $history = Get-Content -LiteralPath $historyPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ('Public history: {0} dated reports, {1} rows, {2} matching system IDs ({3} to {4}).' -f $history.reports,$history.rows,$history.systems_seen,$history.report_dates[0],$history.report_dates[-1])
    Write-Host ('Exploratory near-two-week baseline check: {0} cases; persistence average error {1:N1} percentage points; two-reading trend {2:N1} points.' -f $history.evaluation_targets,$history.mean_absolute_error_percent_points,$history.trend_mean_absolute_error_percent_points)
    Write-Host 'This is a small, correlated retrospective check, not evidence that either forecast is reliable.' -ForegroundColor Yellow
    Write-Host 'See RESERVOIR-PUBLIC-HISTORY.md for methods, sources, and what is still needed.'
} else {
    Write-Host 'Public report history has not been assembled yet.'
}
Write-Host ''
Write-Host 'Enter a county, water-system name, or PWSID to narrow the list; press Enter for all systems.'
$query = (Read-Host 'Filter').Trim()
$rows = @($data.systems)
if ($query) {
    $rows = @($rows | Where-Object {
        $_.county_served -like "*$query*" -or $_.name -like "*$query*" -or $_.pwsid -like "*$query*"
    })
    if (-not $rows.Count) { Write-Host 'No matching system found.'; return }
}

Write-Host ''
Write-Host 'PWSID      System                                      County       Read date    Full    Normal   Report status'
foreach ($system in $rows) {
    switch ($system.trend) {
        'up' { $trend = 'Rising' }
        'up_large' { $trend = 'Rising 10%+' }
        'down' { $trend = 'Falling' }
        'down_large' { $trend = 'Falling 10%+' }
        default { $trend = 'Unchanged' }
    }
    Write-Host ('{0,-10} {1,-44} {2,-12} {3,-12} {4,5:N1}% {5,6:N0}%  {6} ({7})' -f $system.pwsid,$system.name,$system.county_served,$system.reading_date,$system.percent_full,$system.percent_of_normal,$system.status,$trend)
}
Write-Host ''
Write-Host 'No two-week forecast is issued from this report. It contains only one current and one previous reading per system, with uneven dates.' -ForegroundColor Yellow
Write-Host 'A water system can combine reservoirs; percentages are not comparable to a farm well or a specific reservoir.'
Write-Host 'Source: Connecticut DPH Surface Reservoir Capacity Measurements and Trends, 11/12/2024.'
Write-Activity 'Viewed the historical Connecticut DPH surface-water system-capacity snapshot. No reservoir forecast was issued.'
