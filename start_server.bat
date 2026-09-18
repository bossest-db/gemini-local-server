@echo off
chcp 65001 > nul
title Gemini 사설 서버 및 웹 대시보드

echo ========================================================
echo   🚀 Gemini 로컬 사설 서버 & 대시보드 구동 중...
echo ========================================================
echo.

cd /d "C:\Users\yu\gemini-server"

:: 1. Check if port 9223 (Gemini CDP) is open
powershell -Command "if (-not (Get-NetTCPConnection -LocalPort 9223 -ErrorAction SilentlyContinue)) { exit 1 }"
if %errorlevel% neq 0 (
    echo [알림] Gemini가 켜져 있지 않습니다. 원격 디버그 모드로 자동 실행합니다...
    start "" "%LOCALAPPDATA%\Google\Gemini\Gemini.exe" --remote-debugging-port=9223
    timeout /t 3 /nobreak > nul
)

echo [1/2] Gemini 엔진 연결 준비 완료 (Port 9223)
echo [2/2] FastAPI 웹 서버 및 대시보드 실행 (Port 8000)
echo.
echo 🌐 브라우저 대시보드 : http://localhost:8000
echo ⚡ API Swagger 문서   : http://localhost:8000/docs
echo 📁 로컬 저장 보관함   : C:\Users\yu\Documents\Gemini_Archive
echo.
echo 서버가 켜졌습니다. 종료하려면 이 창에서 Ctrl+C를 누르세요.
echo ========================================================
echo.

:: Automatically open browser after 2 seconds
start "" http://localhost:8000

python app.py
pause
