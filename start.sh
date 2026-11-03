#!/usr/bin/env bash
# LibTV-Team 一键启动（Linux / macOS）
# 用法：./start.sh    （首次会自动建 .venv 并安装依赖，之后直接启动面板）
set -e

cd "$(dirname "$0")"

# 选择 python 解释器（要求 >= 3.8）
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,8) else 1)' 2>/dev/null; then
      PY="$c"
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "[错误] 未找到 Python 3.8+，请先安装后重试。" >&2
  exit 1
fi

VENV=.venv
VPY="$VENV/bin/python"
if [ ! -x "$VPY" ]; then
  echo "==> 创建虚拟环境 $VENV ..."
  "$PY" -m venv "$VENV"
fi

echo "==> 安装/更新依赖 ..."
"$VPY" -m pip install --upgrade pip --quiet
"$VPY" -m pip install -r requirements.txt

PORT="${LIBLIB_PORT:-8000}"
HOST="${LIBLIB_HOST:-127.0.0.1}"
export LIBLIB_SERVER_PORT="$PORT"
export LIBLIB_SERVER_PUBLIC_URL="http://127.0.0.1:$PORT"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8="1"

echo ""
echo "==> 面板地址： http://127.0.0.1:$PORT/panel"
echo "==> 管理员默认账号：admin / admin（首次登录后请在「设置」修改密码）"
echo "==> 按 Ctrl+C 停止服务"
echo ""

# 启动后尝试自动打开浏览器（失败不影响服务）
(
  sleep 2
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT/panel" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/panel" >/dev/null 2>&1 &
  fi
) &

exec "$VPY" -m liblib2api.cli serve --host "$HOST" --port "$PORT"
