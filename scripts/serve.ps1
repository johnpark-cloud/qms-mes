# 사내망 서비스: 팀원이 http://<이 PC 이름>:8000 으로 접속한다 (waitress, 무료).
# 사용: powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -HostName QA-PC01 -ListenIp 192.168.0.10 -Port 8000
param(
    [Parameter(Mandatory = $true)][string]$HostName,  # 팀원이 주소창에 칠 이 PC의 이름 또는 IP (여러 개는 쉼표로)
    [string]$ListenIp = "*",  # 사내망 랜카드의 IP를 적으면 그 연결로만 접속을 받는다 (* = 모든 연결: 외부 Wi-Fi·VPN 포함)
    [int]$Port = 8000
)
$proj = Split-Path -Parent $PSScriptRoot
$python = Join-Path $proj ".venv\Scripts\python.exe"
$env:QMS_DEBUG = "0"
$env:QMS_ALLOWED_HOSTS = "$HostName,localhost,127.0.0.1"
Set-Location $proj
& $python manage.py migrate --noinput
& $python manage.py collectstatic --noinput
if ($ListenIp -eq "*") {
    Write-Warning "모든 네트워크 연결에서 접속을 받습니다. 노트북이면 -ListenIp <사내망 IP>를 지정하세요."
}
Write-Host "서비스 시작: http://$($HostName.Split(',')[0]):$Port  (중지: Ctrl+C)"
& (Join-Path $proj ".venv\Scripts\waitress-serve.exe") --listen="${ListenIp}:$Port" config.wsgi:application
