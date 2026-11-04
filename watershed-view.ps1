$catalogPath = Join-Path $PSScriptRoot 'data/watershed-catalog.json'
if (-not (Test-Path -LiteralPath $catalogPath)) {
    Write-Host 'The watershed boundaries have not been prepared yet.'
    return
}
$catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
Write-Host ''
Write-Host 'CONNECTICUT WATERSHEDS' -ForegroundColor Cyan
Write-Host ('Official boundaries loaded: {0} smaller watershed IDs in 8 major areas.' -f $catalog.watershed_count)
Write-Host 'Several separate pieces can belong to the same watershed.'
Write-Host 'Cross-border portions are kept. These are not complete upstream networks.'
Write-Host ''
foreach ($major in $catalog.majors) {
    Write-Host ('  {0}  {1} ({2} smaller watersheds)' -f $major.id, $major.name, $major.watershed_count)
}
Write-Host ''
$basinChoice = Read-Host 'Choose a major area number to see its watersheds, or press Enter to return'
$selected = @($catalog.basins | Where-Object { $_.major_id -eq $basinChoice })
if ($selected.Count -gt 0) {
    $selected | Select-Object @{Name='Watershed number';Expression={$_.id}}, @{Name='Watershed name';Expression={$_.name}}, @{Name='Regional group';Expression={$_.regional_name}} | Format-Table -AutoSize | Out-Host
    Write-Host 'Drought risk: Not calculated yet. Boundaries alone cannot measure dryness.'
    Write-Activity ('Viewed the ' + $selected[0].major_name + ' drainage area using official CT DEEP boundaries. No drought forecast was calculated.')
} elseif ($basinChoice) { Write-Host 'That area number was not found.' }
