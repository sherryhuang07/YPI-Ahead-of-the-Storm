# Download new USGS VegDRI weeks and keep Connecticut summaries (scripts/fetch_vegdri.py).
# Uses the USGS sign-in saved (Windows-encrypted) by Connect USGS EarthExplorer.cmd; it is
# placed in this process's environment only for the download and removed afterwards.
#   vegdri-update.ps1            all missing weeks since 2009 (first run: several hours)
#   vegdri-update.ps1 -Recent    nightly: only weeks not yet downloaded
param([switch]$Recent, [int]$Limit = 0)
$root = $PSScriptRoot
$credentialPath = Join-Path $root 'data\drought\auth\usgs-credentials.xml'
if (-not (Test-Path -LiteralPath $credentialPath)) { Write-Host 'No saved USGS sign-in. Open Connect USGS EarthExplorer.cmd first.' -ForegroundColor Yellow; exit 2 }
$code = 1
try {
    $c = Import-Clixml -LiteralPath $credentialPath
    $env:USGS_USERNAME = $c.UserName; $env:USGS_TOKEN = $c.GetNetworkCredential().Password; $c = $null
    $args2 = @()
    if ($Recent) { $args2 += '--recent' }
    if ($Limit -gt 0) { $args2 += @('--limit', $Limit) }
    & (Join-Path $root '.venv\Scripts\python.exe') -u (Join-Path $root 'scripts\fetch_vegdri.py') @args2
    $code = $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Yellow
} finally {
    Remove-Item Env:USGS_TOKEN, Env:USGS_USERNAME -ErrorAction SilentlyContinue
}
exit $code
