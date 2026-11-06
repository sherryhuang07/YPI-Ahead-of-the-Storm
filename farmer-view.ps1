$Host.UI.RawUI.WindowTitle = 'Ahead of the Storm | Farmer View'
$activityPath = Join-Path $PSScriptRoot 'activity.log'
function Write-Activity([string]$Message) {
    $stamp = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time').ToString('yyyy-MM-dd h:mm:ss tt')
    Add-Content -LiteralPath $activityPath -Value "$stamp ET | $Message"
}
Write-Activity 'The farmer view opened. Historical inputs and separate experimental forecasts are available; operational accuracy is not established.'
try {
    while ($true) {
        Clear-Host
        Write-Host 'AHEAD OF THE STORM' -ForegroundColor Green
        Write-Host 'Farmer View | Connecticut agricultural water stress'
        Write-Host ''
        Write-Host 'RESEARCH VERSION - Experimental forecasts; accuracy not established.' -ForegroundColor Yellow
        Write-Host ''
        Write-Host 'Pilot farm: Yale Farm, New Haven - boundaries need review'
        Write-Host 'Next 14 days: NOAA rainfall guidance under option 7'
        Write-Host 'Too much water: Not assessed yet'
        Write-Host 'Too little water: Not assessed yet'
        Write-Host 'Farm-specific strategies: Waiting for farm details and evidence'
        Write-Host ''
        Write-Host 'Type a number, then press Enter:'
        Write-Host '  1  Check the two-week outlook'
        Write-Host '  2  See what we need to know about your farm'
        Write-Host '  3  See which information sources are connected'
        Write-Host '  4  Explore Connecticut watersheds'
        Write-Host '  5  See Yale Farm boundaries and mapping evidence'
        Write-Host '  6  Explore statewide farm-boundary candidates by town'
        Write-Host '  7  See cumulative precipitation for farms and watersheds'
        Write-Host '  8  See groundwater readings and monitoring gaps'
        Write-Host '  9  See streamflow and historical percentile bands'
        Write-Host '  10 See streamflow forecasts trained on longer histories'
        Write-Host '  11 See the daily forecast-versus-observation check'
        Write-Host '  12 Explore connected stream gauges in neighboring states'
        Write-Host '  13 See drinking-water system reservoir capacity'
        Write-Host '  14 See the separate root-zone soil moisture model'
        Write-Host '  15 See the forest fire danger forecast'
        Write-Host '  16 See the coastal water temperature forecast'
        Write-Host '  17 See the combined drought forecast'
        Write-Host '  Q  Close this window'
        Write-Host ''
        $choice = Read-Host 'Your choice'
        if ($choice -eq 'q') { break }
        Write-Host ''
        switch ($choice) {
            '1' { . (Join-Path $PSScriptRoot 'forecast-view.ps1') }
            '2' {
                Write-Host 'In a later step, we will add a place to enter:'
                Write-Host '  Your Connecticut town and field locations'
                Write-Host '  Crops, planting dates, and growth stages'
                Write-Host '  Soil information and drainage conditions'
                Write-Host '  Available irrigation, water supplies, equipment, and local support'
                Write-Host '  Sensor locations and measurements'
                Write-Host 'No farm details are being collected in this starter version.'
                Write-Activity 'The farmer viewed the farm setup checklist. No farm details were collected.'
            }
            '3' {
                Write-Host 'Official CT DEEP watershed boundaries: Loaded locally'
                Write-Host 'Statewide farm boundary candidates: Available under option 6'
                Write-Host 'PRISM history and NOAA live precipitation forecast: See option 7'
                Write-Host 'USGS groundwater observations: See option 8 for coverage and dates'
                Write-Host 'USGS streamflow and seasonal statistics: See option 9'
                Write-Host 'DPH drinking-water system reservoir capacity: See option 13; historical snapshot only'
                Write-Host 'Root-zone soil moisture: Separate research forecast under option 14 (NASA NLDAS inputs; refresh with Refresh Soil Moisture.cmd)'
                Write-Host 'On-farm sensors across Connecticut: Not connected'
                Write-Host 'Climate research papers: Not added'
                Write-Host 'Local resources and assistance: Not added'
                Write-Host 'Separate 14-day models: Experimental only; see option 1 for errors and coverage limits'
                Write-Activity 'The farmer checked sources. Watersheds, farm candidates, and the PRISM importer are available. Sensors and forecasts await setup.'
            }
            '4' { . (Join-Path $PSScriptRoot 'watershed-view.ps1') }
            '5' { . (Join-Path $PSScriptRoot 'farm-view.ps1') }
            '6' { . (Join-Path $PSScriptRoot 'statewide-view.ps1') }
            '7' { . (Join-Path $PSScriptRoot 'precipitation-view.ps1') }
            '8' { . (Join-Path $PSScriptRoot 'groundwater-view.ps1') }
            '9' { . (Join-Path $PSScriptRoot 'streamflow-view.ps1') }
            '10' { . (Join-Path $PSScriptRoot 'trained-streamflow-view.ps1') }
            '11' { . (Join-Path $PSScriptRoot 'prospective-view.ps1') }
            '12' { . (Join-Path $PSScriptRoot 'regional-streamflow-view.ps1') }
            '13' { . (Join-Path $PSScriptRoot 'reservoir-view.ps1') }
            '14' { . (Join-Path $PSScriptRoot 'root-zone-view.ps1') }
            '15' { . (Join-Path $PSScriptRoot 'fire-danger-view.ps1') }
            '16' { . (Join-Path $PSScriptRoot 'water-temp-view.ps1') }
            '17' { . (Join-Path $PSScriptRoot 'drought-view.ps1') }
            default { Write-Host 'Please choose a number from 1 to 17, or Q.' }
        }
        Write-Host ''
        Read-Host 'Press Enter to return to the main screen' | Out-Null
    }
} finally {
    Write-Activity 'The farmer view closed.'
}
