$profilePath = Join-Path $PSScriptRoot 'data/yale-farm/profile.json'
if (-not (Test-Path -LiteralPath $profilePath)) { Write-Host 'The farm map has not been prepared yet.'; return }
$farm = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
Write-Host ''
Write-Host 'YALE FARM | FIRST FARM PROFILE' -ForegroundColor Cyan
Write-Host $farm.address
Write-Host ''
Write-Host 'Mapped property: Parcel 14057, listed at 335 Prospect Street'
Write-Host 'Watershed: Mill River, within the South Central Coast drainage area'
Write-Host ('Public farm outline: about {0:N2} acres; Yale describes roughly 1 acre' -f $farm.provisional_outline_acres)
Write-Host 'Boundary status: Provisional - your farm team needs to review it'
Write-Host ''
Write-Host 'Available evidence:'
Write-Host '  Assessor property boundaries with 2026 collection-year labels'
Write-Host '  Detailed 2023 aerial photograph'
Write-Host '  October 23, 2026 satellite image (10-meter pixels)'
Write-Host '  Public OpenStreetMap farm outline, last edited in 2020'
Write-Host ''
Write-Host 'Still needed: Confirm growing beds, tunnels, paths, and operated land.'
Write-Host 'Then add crops, soil, irrigation resources, and sensor locations.'
Write-Host 'No planted acreage, water demand, or personalized actions are calculated yet.'
Write-Activity 'Viewed Yale Farm boundary evidence: public farm outline, assessor parcels, aerial imagery, satellite crop, and Mill River watershed match. Farm boundaries still need review.'
