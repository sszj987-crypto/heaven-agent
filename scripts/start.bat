@echo off
setlocal enabledelayedexpansion

set ROOT=%~dp0..
set PID_FILE=%ROOT%\.pids
set LOG_DIR=%ROOT%\log

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 检查是否已在运行（通过端口占用）
netstat -ano | findstr ":8326" >nul 2>&1
if %errorlevel% equ 0 (
    echo 后端端口 8326 已被占用，请先停止已有服务
    echo 执行: scripts\stop.bat 或手动结束占用进程
    exit /b 1
)

echo ===== 启动 Heaven Agent =====

REM 首次运行或依赖清单变化时自动创建/修复环境并安装核心依赖
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3.13 "%ROOT%\scripts\bootstrap.py" || py -3.12 "%ROOT%\scripts\bootstrap.py" || py -3.11 "%ROOT%\scripts\bootstrap.py"
) else (
    python "%ROOT%\scripts\bootstrap.py"
)
if %errorlevel% neq 0 exit /b 1

set PYTHON=%ROOT%\.venv\Scripts\python.exe

REM 启动后端
start "Heaven-Agent-Backend" /B "%PYTHON%" -m uvicorn src.main:app --host 127.0.0.1 --port 8326 > "%LOG_DIR%\backend.log" 2>&1
echo 后端已启动 (port: 8326)，等待就绪...

REM 等待后端健康检查通过（最多 60 秒）
for /L %%i in (1,1,60) do (
    powershell -Command "try { Invoke-WebRequest -Uri http://localhost:8326/ -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo 后端就绪 (耗时 %%is^)
        goto :backend_ready
    )
    timeout /t 1 /nobreak >nul
)
echo 后端启动超时，请检查日志: %LOG_DIR%\backend.log
exit /b 1

:backend_ready

REM 启动前端
cd /d "%ROOT%\frontend"
start "Heaven-Agent-Frontend" /B npm run dev -- -p 3326 > "%LOG_DIR%\frontend.log" 2>&1
echo 前端已启动 (port: 3326, log: %LOG_DIR%\frontend.log)

cd /d "%ROOT%"

REM 记录 PID（通过端口查找，Windows 上 PID 获取不如 Unix 可靠，用端口记录替代）
powershell -Command "Get-NetTCPConnection -LocalPort 8326 | Select-Object -ExpandProperty OwningProcess" > "%PID_FILE%"
powershell -Command "Get-NetTCPConnection -LocalPort 3326 | Select-Object -ExpandProperty OwningProcess" >> "%PID_FILE%"

echo.
echo ===== Heaven Agent 已启动 =====
echo   前端: http://localhost:3326
echo   后端: http://localhost:8326
echo   日志: %LOG_DIR%\
echo   停止服务: scripts\stop.bat
