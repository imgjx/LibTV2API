#!/usr/bin/env bash
# Liblib2API 一键启动（Linux / macOS）
# 用法：./start.sh    （首次会自动建 .venv 并安装依赖，之后直接启动面板）
set -e

cd "$(dirname "$0")"

# 选择 python 解释器
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

VENV=.venv
if [ ! -d "$VENV" ]; then
  echo "==> 创建虚拟环境 $VENV ..."
  "$PY" -m venv "$VENV"
fi

# 激活虚拟环境
source "$VENV/bin/activate"

echo "==> 安装依赖 ..."
pip install -q -r requirements.txt

PORT="${LIBLIB_PORT:-8000}"
HOST="${LIBLIB_HOST:-0.0.0.0}"
export LIBLIB_SERVER_PORT="$PORT"
export LIBLIB_SERVER_PUBLIC_URL="http://127.0.0.1:$PORT"

echo "==> 启动面板： http://127.0.0.1:$PORT/panel"
# 启动后尝试自动打开浏览器（失败不影响服务）
(
  sleep 2
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT/panel" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/panel" >/dev/null 2>&1 &
  fi
) &

exec python -m liblib2api.cli serve --host "$HOST" --port "$PORT"
