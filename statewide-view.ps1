$summaryPath = Join-Path $PSScriptRoot 'outputs/statewide/summary.json'
if (-not (Test-Path -LiteralPath $summaryPath)) {
    Write-Host 'The statewide inventory is still being prepared. Activity appears in Behind the Scenes.'
    return
}
$summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
$towns = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'outputs/statewide/town-coverage.json') -Raw | ConvertFrom-Json
Write-Host ''
Write-Host 'CONNECTICUT FARM BOUNDARY REVIEW' -ForegroundColor Cyan
Write-Host ('All {0} towns checked against the selected public sources.' -f $summary.towns_processed)
Write-Host ('{0:N0} candidate outlines and locations; these are not a count of farms.' -f $summary.candidate_records)
Write-Host ('{0:N0} property keys linked or screened; {1:N0} directory listings retained.' -f $summary.unique_property_keys, $summary.directory_listings)
Write-Host 'Every boundary still needs review. Farms missing from every source are unknown.' -ForegroundColor Yellow
Write-Host ''
$townName = Read-Host 'Enter a Connecticut town name, or press Enter to return'
if (-not $townName) { return }
$town = @($towns | Where-Object { $_.town -eq $townName.Trim() })
if ($town.Count -ne 1) {
    Write-Host 'Town not found. Use the municipality name, such as New Haven or Mansfield.'
    return
}
$town = $town[0]
$fileName = '{0:000}.json' -f [int]$town.town_number
$page = Get-Content -LiteralPath (Join-Path $PSScriptRoot ('outputs/statewide/towns/' + $fileName)) -Raw | ConvertFrom-Json
Write-Host ''
Write-Host $town.town -ForegroundColor Green
Write-Host ('Satellite field candidates: {0}; public mapped outlines/locations: {1}' -f $town.satellite_candidates, $town.public_mapped_candidates)
Write-Host ('Agricultural property candidates: {0}; directory address leads: {1}' -f $town.agricultural_property_candidates, $town.directory_leads)
Write-Host ('Property records without a land-use description: {0:N0} of {1:N0}' -f $town.parcel_records_missing_use_description, $town.parcel_records_total)
Write-Host 'Overlapping source records can describe the same land. Do not add them as farms.'
Write-Activity ('Opened statewide boundary review for ' + $town.town + '. All candidates remain unverified.')
$items = @($page.candidates)
$offset = 0
while ($items.Count -gt 0) {
    Write-Host ''
    $last = [Math]::Min($offset + 12, $items.Count)
    for ($i = $offset; $i -lt $last; $i++) {
        $item = $items[$i]
        $label = $item.name
        if (-not $label) { $label = $item.candidate_id }
        Write-Host ('  {0}. {1} | {2}' -f ($i + 1), $label, $item.source)
    }
    Write-Host ('Showing {0}-{1} of {2}. N = next, P = previous, number = details, Enter = return.' -f ($offset + 1), $last, $items.Count)
    $answer = Read-Host 'Your choice'
    if (-not $answer) { break }
    if ($answer -eq 'n') { if ($last -lt $items.Count) { $offset += 12 }; continue }
    if ($answer -eq 'p') { $offset = [Math]::Max(0, $offset - 12); continue }
    $selectedNumber = 0
    if ([int]::TryParse($answer, [ref]$selectedNumber) -and $selectedNumber -ge 1 -and $selectedNumber -le $items.Count) {
        $item = $items[$selectedNumber - 1]
        Write-Host ''
        Write-Host ('Candidate: ' + $item.candidate_id)
        Write-Host ('Evidence: ' + $item.source)
        Write-Host ('Property addresses: ' + ($item.parcel_addresses -join '; '))
        Write-Host ('Watershed numbers: ' + ($item.watershed_ids -join ', '))
        if ($null -ne $item.ct_area_acres) { Write-Host ('Mapped outline: {0:N2} acres; not confirmed planted acreage' -f $item.ct_area_acres) }
        Write-Host ('Needs attention: ' + ($item.review_flags -join '; '))
        Write-Host 'Farmer confirmation: Still needed. No tailored strategy is generated from this outline.'
        Write-Host ('Source: ' + $item.source_url)
    } else { Write-Host 'Choose a listed number, N, P, or press Enter.' }
}
if ($items.Count -eq 0) { Write-Host 'No field outlines were found in these sources. This does not mean there are no farms.' }
