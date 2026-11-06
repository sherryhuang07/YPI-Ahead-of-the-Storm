param([switch]$UseSaved)
$ErrorActionPreference = 'Stop'
$credentialFolder = Join-Path $PSScriptRoot 'data\root-zone\auth'
$credentialPath = Join-Path $credentialFolder 'earthdata-credentials.xml'
try {
    if ($UseSaved) {
        if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'No saved NASA sign-in. Open Connect NASA Earthdata.cmd first.' }
        $nasaCredential = Import-Clixml -LiteralPath $credentialPath
    } else {
        $Host.UI.RawUI.WindowTitle = 'Connect NASA Earthdata | Ahead of the Storm'
        Write-Host 'CONNECT YOUR NASA EARTHDATA ACCOUNT' -ForegroundColor Green
        Write-Host 'Enter your credentials here, not in chat. The password will be hidden.'
        Write-Host 'After a successful check, Windows will encrypt the saved password for your Windows account.'
        Write-Host 'This connects the separate soil-moisture project. It does not change the drought model.'
        Write-Host ''
        $nasaUsername = Read-Host 'Earthdata username (not necessarily your email)'
        $nasaPassword = Read-Host 'Earthdata password' -AsSecureString
        if ([string]::IsNullOrWhiteSpace($nasaUsername) -or $nasaPassword.Length -eq 0) { throw 'Sign-in cancelled: username or password was empty.' }
        $nasaCredential = New-Object System.Management.Automation.PSCredential ($nasaUsername, $nasaPassword)
    }
    $env:EARTHDATA_USERNAME = $nasaCredential.UserName
    $env:EARTHDATA_PASSWORD = $nasaCredential.GetNetworkCredential().Password
    Write-Host 'Checking your sign-in with NASA...'
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'scripts\check_earthdata_login.py')
    if ($LASTEXITCODE -ne 0) { throw 'Connection was not verified. No new credentials were saved.' }
    if (-not $UseSaved) {
        New-Item -ItemType Directory -Force -Path $credentialFolder | Out-Null
        $nasaCredential | Export-Clixml -LiteralPath $credentialPath
    }
    Write-Host 'Connected. Your sign-in was verified and saved locally.' -ForegroundColor Green
    Write-Host 'Tell the chat the connection is complete so dataset downloads can be checked.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Yellow
} finally {
    Remove-Item Env:EARTHDATA_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:EARTHDATA_USERNAME -ErrorAction SilentlyContinue
    $nasaCredential = $null
    $nasaPassword = $null
    if (-not $UseSaved) { Read-Host 'Press Enter to close this window' | Out-Null }
}
