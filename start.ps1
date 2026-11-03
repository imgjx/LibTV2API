# Liblib2API 一键启动（Windows）
# 用法：双击 start.bat（或右键「使用 PowerShell 运行」）。
# 首次运行会自动创建 .venv 并安装依赖，之后直接启动面板。
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$venv = Join-Path $root ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "==> 创建虚拟环境 .venv ..."
    python -m venv $venv
}

$activate = Join-Path $venv "Scripts\Activate.ps1"
& $activate

Write-Host "==> 安装依赖 ..."
pip install -q -r (Join-Path $root "requirements.txt")

$port = if ($env:LIBLIB_PORT) { $env:LIBLIB_PORT } else { "8000" }
$host_ = if ($env:LIBLIB_HOST) { $env:LIBLIB_HOST } else { "0.0.0.0" }
$env:LIBLIB_SERVER_PORT = $port
$env:LIBLIB_SERVER_PUBLIC_URL = "http://127.0.0.1:$port"

Write-Host "==> 启动面板： http://127.0.0.1:$port/panel"
# 尝试自动打开浏览器
Start-Process "http://127.0.0.1:$port/panel" -ErrorAction SilentlyContinue

python -m liblib2api.cli serve --host $host_ --port $port
