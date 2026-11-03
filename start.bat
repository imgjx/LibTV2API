@echo off
chcp 65001 >nul
setlocal
REM LibTV-Team 一键启动（Windows 双击运行）
REM 以「绕过执行策略」方式调用 start.ps1，避免 PowerShell 脚本被执行策略阻止。
where powershell >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Windows PowerShell，无法启动。
    echo 可在终端执行：py -3 -m venv .venv
    echo             .venv\Scripts\python -m pip install -r requirements.txt
    echo             .venv\Scripts\python -m liblib2api.cli serve --port 8000
    goto :done
)
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请查看上方日志。常见原因：未安装 Python 3.8+ 或网络无法访问 PyPI。
    echo 可手动执行：py -3 -m venv .venv
    echo             .venv\Scripts\python -m pip install -r requirements.txt
    echo             .venv\Scripts\python -m liblib2api.cli serve --port 8000
    echo.
)
:done
pause
