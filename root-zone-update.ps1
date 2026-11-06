param(
    [ValidateSet('all','inputs','forecast','check-archive')][string]$Step = 'all'
)
# Assemble recent daily root-zone inputs from NASA NLDAS-2 and issue the standalone
# soil-moisture forecast. Uses the Windows-encrypted sign-in saved by
# "Connect NASA Earthdata.cmd"; the password is passed to the Python child only.
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$scripts = Join-Path $PSScriptRoot 'scripts'
$credentialPath = Join-Path $PSScriptRoot 'data\root-zone\auth\earthdata-credentials.xml'
$code = 0
Push-Location $scripts
try {
    if ($Step -ne 'forecast') {
        if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'NASA sign-in not saved yet. Open "Connect NASA Earthdata.cmd" first.' }
        $nasaCredential = Import-Clixml -LiteralPath $credentialPath
        $env:EARTHDATA_USERNAME = $nasaCredential.UserName
        $env:EARTHDATA_PASSWORD = $nasaCredential.GetNetworkCredential().Password
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data\root-zone\basins\weights.json'))) {
            & $python 'build_root_zone_basins.py'; if ($LASTEXITCODE) { throw 'Watershed boundary step failed.' }
        }
        if ($Step -eq 'check-archive') {
            & $python 'assemble_root_zone_inputs.py' 'check-archive' '--offsets' 0 1 5 6 7
        } else {
            & $python 'assemble_root_zone_inputs.py' 'live'
        }
        $code = $LASTEXITCODE
    }
    if ($code -eq 0 -and ($Step -eq 'all' -or $Step -eq 'forecast')) {
        & $python 'forecast_root_zone.py'; $code = $LASTEXITCODE
    }
} finally {
    Remove-Item Env:EARTHDATA_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:EARTHDATA_USERNAME -ErrorAction SilentlyContinue
    $nasaCredential = $null
    Pop-Location
}
exit $code
