@echo off
REM Liblib2API 一键启动（Windows 双击运行）
REM 该脚本以「绕过执行策略」方式调用 start.ps1，避免 PowerShell 脚本被阻止。
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start.ps1"
pause
