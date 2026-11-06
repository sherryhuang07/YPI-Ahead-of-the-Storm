param([switch]$UseSaved)
$ErrorActionPreference = 'Stop'
$credentialFolder = Join-Path $PSScriptRoot 'data\drought\auth'
$credentialPath = Join-Path $credentialFolder 'usgs-credentials.xml'
try {
    if ($UseSaved) {
        if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'No saved USGS sign-in. Open Connect USGS EarthExplorer.cmd first.' }
        $usgsCredential = Import-Clixml -LiteralPath $credentialPath
    } else {
        $Host.UI.RawUI.WindowTitle = 'Connect USGS EarthExplorer | Ahead of the Storm'
        Write-Host 'CONNECT YOUR USGS EARTHEXPLORER ACCOUNT (for VegDRI drought data)' -ForegroundColor Green
        Write-Host 'Enter your details here, not in chat. The token will be hidden.'
        Write-Host 'Windows will encrypt the saved token for your Windows account after it is verified.'
        Write-Host ''
        Write-Host 'You need: your USGS username, and an APPLICATION TOKEN (not your password),'
        Write-Host 'created at https://ers.cr.usgs.gov/password/appgenerate after M2M access is approved.'
        Write-Host ''
        $usgsUsername = Read-Host 'USGS username'
        $usgsToken = Read-Host 'USGS application token' -AsSecureString
        if ([string]::IsNullOrWhiteSpace($usgsUsername) -or $usgsToken.Length -eq 0) { throw 'Cancelled: username or token was empty.' }
        $usgsCredential = New-Object System.Management.Automation.PSCredential ($usgsUsername, $usgsToken)
    }
    $env:USGS_USERNAME = $usgsCredential.UserName
    $env:USGS_TOKEN = $usgsCredential.GetNetworkCredential().Password
    Write-Host 'Checking your sign-in with USGS...'
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'scripts\check_usgs_login.py')
    if ($LASTEXITCODE -ne 0) { throw 'Connection was not verified. Nothing new was saved.' }
    if (-not $UseSaved) {
        New-Item -ItemType Directory -Force -Path $credentialFolder | Out-Null
        $usgsCredential | Export-Clixml -LiteralPath $credentialPath
    }
    Write-Host 'Connected. Your USGS sign-in was verified and saved locally.' -ForegroundColor Green
    Write-Host 'Tell the chat the USGS connection is complete so VegDRI can be downloaded.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Yellow
} finally {
    Remove-Item Env:USGS_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:USGS_USERNAME -ErrorAction SilentlyContinue
    $usgsCredential = $null
    $usgsToken = $null
    if (-not $UseSaved) { Read-Host 'Press Enter to close this window' | Out-Null }
}
