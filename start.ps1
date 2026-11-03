# LibTV-Team 一键启动（Windows）
# 用法：双击 start.bat（或右键「使用 PowerShell 运行」）。
# 首次运行会自动创建 .venv 并安装依赖，之后直接启动面板。
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# 强制 UTF-8，避免中文输出乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[错误] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

# ---- 探测可用的 Python（兼容 py 启动器 / python3 / python）----
$python = $null
$pyArgs = @()
$cands = @(
    @{ exe = "py";      args = @("-3") },
    @{ exe = "python";  args = @() },
    @{ exe = "python3"; args = @() }
)
foreach ($c in $cands) {
    $cmd = Get-Command $c.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $exe = $cmd.Source
        $args = $c.args
        try {
            $ver = & $exe @args -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
            if ($LASTEXITCODE -eq 0 -and [int]$ver -ge 308) {
                $python = $exe
                $pyArgs = $args
                break
            }
        } catch {}
    }
}
if (-not $python) {
    Fail "未找到 Python 3.8+。请先安装 Python（https://www.python.org/downloads/），安装时勾选 Add Python to PATH。"
}

Write-Host "==> 使用 Python: $python $($pyArgs -join ' ')" -ForegroundColor DarkGray

$venv = Join-Path $root ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $vpy)) {
    Write-Host "==> 创建虚拟环境 .venv ..."
    & $python @pyArgs -m venv $venv
    if (-not (Test-Path $vpy)) {
        Fail "创建虚拟环境失败，请确认已安装 Python 且包含 venv 模块。"
    }
}

Write-Host "==> 安装/更新依赖 ..."
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[警告] 依赖安装返回非零状态，继续尝试启动 ..." -ForegroundColor Yellow
}

$port = if ($env:LIBLIB_PORT) { $env:LIBLIB_PORT } else { "8000" }
$host_ = if ($env:LIBLIB_HOST) { $env:LIBLIB_HOST } else { "127.0.0.1" }
$env:LIBLIB_SERVER_PORT = $port
$env:LIBLIB_SERVER_PUBLIC_URL = "http://127.0.0.1:$port"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host ""
Write-Host "==> 面板地址： http://127.0.0.1:$port/panel" -ForegroundColor Green
Write-Host "==> 管理员默认账号：admin / admin（首次登录后请在「设置」修改密码）" -ForegroundColor Green
Write-Host "==> 按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""

Start-Sleep -Milliseconds 800
Start-Process "http://127.0.0.1:$port/panel" -ErrorAction SilentlyContinue

& $vpy -m liblib2api.cli serve --host $host_ --port $port
