# Adds retry times to the two daily forecast tasks so a run missed while the computer
# slept (or stopped in its first seconds after waking) gets another chance the same day.
# Night part: 12:05 AM, retry 5:00 AM. Morning part: 6:30 AM, retries 9:00 AM and 1:00 PM.
# A part that already completed today exits immediately, and forecasts are sealed once per
# day, so retries never duplicate anything. Only these two tasks are changed.
$ErrorActionPreference = 'Stop'
try {
    Set-ScheduledTask -TaskName 'Ahead of the Storm - Daily Forecasts (night)' -Trigger @(
        (New-ScheduledTaskTrigger -Daily -At '12:05 AM'), (New-ScheduledTaskTrigger -Daily -At '5:00 AM')) | Out-Null
    Set-ScheduledTask -TaskName 'Ahead of the Storm - Daily Forecasts (morning)' -Trigger @(
        (New-ScheduledTaskTrigger -Daily -At '6:30 AM'), (New-ScheduledTaskTrigger -Daily -At '9:00 AM'), (New-ScheduledTaskTrigger -Daily -At '1:00 PM')) | Out-Null
    Write-Host 'Schedule updated:' -ForegroundColor Green
    Get-ScheduledTask -TaskName 'Ahead of the Storm*' | ForEach-Object {
        '  {0}: {1}' -f $_.TaskName, (($_.Triggers | ForEach-Object { ([DateTime]$_.StartBoundary).ToString('h:mm tt') }) -join ', ')
    }
} catch {
    Write-Host ('Could not update the schedule: ' + $_.Exception.Message) -ForegroundColor Yellow
}
