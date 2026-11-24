@echo off
chcp 65001 > nul
rem 더블클릭으로 QMS+MES 서버를 켠다. 끌 때는 이 창에서 Ctrl+C 또는 창 닫기.
cd /d "%~dp0"

rem 적용할 DB 갱신이 있을 때만 먼저 백업한다(30일 지난 백업은 backup 명령이 지운다).
if not defined QMS_BACKUP_DIR set "QMS_BACKUP_DIR=%USERPROFILE%\qms-backup"
echo [1/3] DB 갱신이 필요한지 확인 중...
".venv\Scripts\python.exe" manage.py migrate --check > nul 2>&1
if errorlevel 1 (
    echo       갱신할 내용이 있어 먼저 백업합니다: %QMS_BACKUP_DIR%
    ".venv\Scripts\python.exe" manage.py backup "%QMS_BACKUP_DIR%"
    if errorlevel 1 (
        echo.
        echo 백업에 실패해 DB 갱신을 하지 않았습니다. 위 오류 내용을 확인하세요.
        pause
        exit /b 1
    )
)

echo [2/3] DB 구조 확인 중 (코드 업데이트 후 migrate 누락 방지)...
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo DB 갱신에 실패했습니다. 위 오류 내용을 확인하세요.
    pause
    exit /b 1
)

echo [3/3] 서버 시작: http://127.0.0.1:8000/  (3초 뒤 브라우저가 열립니다)
echo 끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
start "" cmd /c "timeout /t 3 > nul & start http://127.0.0.1:8000/"
".venv\Scripts\python.exe" manage.py runserver

echo.
echo 서버가 멈췄습니다. 이미 켜져 있었다면 "port is already in use" 문구가 보입니다.
pause
