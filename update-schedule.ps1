# Keeps the two daily forecast tasks running even when the laptop sleeps or hibernates.
# Night part: 12:05 AM, retry 5:00 AM. Morning part: 6:30 AM, retries 9:00 AM and 1:00 PM.
# Both also run when you sign in or unlock the computer: on battery the laptop hibernates
# overnight, so the first unlock of the day catches up whatever was missed. A part that
# already completed today exits at once, runs outside allowed hours are skipped, and
# forecasts are sealed once per day, so extra starts never duplicate anything.
# Only these two tasks are changed.
$ErrorActionPreference = 'Stop'
try {
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $unlockClass = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskSessionStateChangeTrigger'
    function Extra { @((New-ScheduledTaskTrigger -AtLogOn -User $user),
                       (New-CimInstance -CimClass $unlockClass -ClientOnly -Property @{ StateChange = 8; UserId = $user; Enabled = $true })) }   # 8 = session unlock
    # Launch through the classic console host in headless mode: no window at all. With Windows
    # Terminal as the default terminal, a "hidden" PowerShell still opened a visible window, and
    # closing it killed the run (exit 0xC000013A).
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    function Act($part) { New-ScheduledTaskAction -Execute "$env:WINDIR\System32\conhost.exe" -WorkingDirectory $root `
        -Argument ('--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $root 'daily-forecasts.ps1') + '" -Part ' + $part + ' -Scheduled') }
    Set-ScheduledTask -TaskName 'Ahead of the Storm - Daily Forecasts (night)' -Action (Act 'night') -Trigger (@(
        (New-ScheduledTaskTrigger -Daily -At '12:05 AM'), (New-ScheduledTaskTrigger -Daily -At '5:00 AM')) + (Extra)) | Out-Null
    Set-ScheduledTask -TaskName 'Ahead of the Storm - Daily Forecasts (morning)' -Action (Act 'morning') -Trigger (@(
        (New-ScheduledTaskTrigger -Daily -At '6:30 AM'), (New-ScheduledTaskTrigger -Daily -At '9:00 AM'), (New-ScheduledTaskTrigger -Daily -At '1:00 PM')) + (Extra)) | Out-Null
    Write-Host 'Schedule updated:' -ForegroundColor Green
    Get-ScheduledTask -TaskName 'Ahead of the Storm*' | ForEach-Object {
        $t = $_.Triggers | ForEach-Object {
            if ($_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger') { 'at sign-in' }
            elseif ($_.CimClass.CimClassName -eq 'MSFT_TaskSessionStateChangeTrigger') { 'on unlock' }
            else { ([DateTime]$_.StartBoundary).ToString('h:mm tt') } }
        '  {0}: {1}' -f $_.TaskName, ($t -join ', ')
        '    runs: ' + $_.Actions[0].Execute + ' ' + $_.Actions[0].Arguments.Substring(0, 10) + '... (no window)'
    }
} catch {
    Write-Host ('Could not update the schedule: ' + $_.Exception.Message) -ForegroundColor Yellow
}
