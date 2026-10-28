# 매일 자동 백업을 Windows 작업 스케줄러에 등록한다 (비용 0원, OS 내장 기능).
# 사용: powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1 -Dest "\\NAS\quality\qms-backup" -Time 18:00
param(
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$Time = "18:00"
)
$proj = Split-Path -Parent $PSScriptRoot
$python = Join-Path $proj ".venv\Scripts\python.exe"

# 백업에는 전 직원의 연차·급여 DB와 명세서가 들어 있다: 폴더를 이 계정만 읽고 쓰게 잠근다
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
icacls $Dest /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "백업 폴더 권한을 잠그지 못했습니다. IT팀에 '$Dest' 폴더를 이 계정 전용으로 설정해 달라고 요청하세요."
}

$action = New-ScheduledTaskAction -Execute $python -Argument "manage.py backup `"$Dest`"" -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable  # PC가 꺼져 있었으면 켜질 때 실행
Register-ScheduledTask -TaskName "QMS-Backup" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "등록 완료: 매일 $Time 에 $Dest 로 백업합니다. (폴더 접근: ${env:USERNAME} 전용)"
