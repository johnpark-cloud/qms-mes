# manage.py 명령을 매일 정해진 시각에 실행하도록 Windows 작업 스케줄러에 등록한다 (비용 0원, OS 내장 기능).
# 예: 기한 알림  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Command notify -Time 08:30
#     자동수집   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Command collect -Time 07:00
# 알림 수신처(QMS_NOTIFY_EMAILS, QMS_TEAMS_WEBHOOK)와 메일 서버(QMS_SMTP_*)는 Windows "사용자 환경 변수"에 넣어 둔다.
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$Arguments = "",
    [string]$Time = "08:30"
)
$proj = Split-Path -Parent $PSScriptRoot
$python = Join-Path $proj ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $python -Argument ("manage.py $Command $Arguments").Trim() -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable  # PC가 꺼져 있었으면 켜질 때 실행
Register-ScheduledTask -TaskName "QMS-$Command" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "등록 완료: 매일 $Time 에 manage.py $Command $Arguments"
