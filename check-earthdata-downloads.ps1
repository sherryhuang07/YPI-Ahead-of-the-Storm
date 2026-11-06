$ErrorActionPreference = 'Stop'
$credentialPath = Join-Path $PSScriptRoot 'data\root-zone\auth\earthdata-credentials.xml'
try {
    $nasaCredential = Import-Clixml -LiteralPath $credentialPath
    $env:EARTHDATA_USERNAME = $nasaCredential.UserName
    $env:EARTHDATA_PASSWORD = $nasaCredential.GetNetworkCredential().Password
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'scripts\check_earthdata_downloads.py')
    $checkExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:EARTHDATA_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:EARTHDATA_USERNAME -ErrorAction SilentlyContinue
    $nasaCredential = $null
}
exit $checkExitCode
