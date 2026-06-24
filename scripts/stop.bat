@echo off

echo ===== 停止 VoiceFromHeaven =====

REM 通过端口结束进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8326.*LISTENING"') do (
    echo 停止 PID %%a (后端, port 8326) ...
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3326.*LISTENING"') do (
    echo 停止 PID %%a (前端, port 3326) ...
    taskkill /PID %%a /F >nul 2>&1
)

REM 清理 PID 文件
set ROOT=%~dp0..
if exist "%ROOT%\.pids" del "%ROOT%\.pids"

REM 清空日志
type nul > "%ROOT%\log\backend.log" 2>nul
type nul > "%ROOT%\log\frontend.log" 2>nul

echo ===== 已停止 =====
