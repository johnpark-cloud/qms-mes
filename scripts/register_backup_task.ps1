# 매일 자동 백업을 Windows 작업 스케줄러에 등록한다 (비용 0원, OS 내장 기능).
# 사용: powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1 -Dest "\\NAS\quality\qms-backup" -Time 18:00
param(
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$Time = "18:00"
)
$proj = Split-Path -Parent $PSScriptRoot
$python = Join-Path $proj ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $python -Argument "manage.py backup `"$Dest`"" -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable  # PC가 꺼져 있었으면 켜질 때 실행
Register-ScheduledTask -TaskName "QMS-Backup" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "등록 완료: 매일 $Time 에 $Dest 로 백업합니다."
