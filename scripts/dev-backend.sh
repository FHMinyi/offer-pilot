#!/usr/bin/env bash
# 启动后端开发服务器（FastAPI + uvicorn）。
# 首次运行会自动创建虚拟环境并安装依赖。
# 端口可通过环境变量覆盖：PORT=8010 ./scripts/dev-backend.sh
set -euo pipefail

cd "$(dirname "$0")/../backend"
PORT="${PORT:-7968}"

if [ ! -d .venv ]; then
  echo "[backend] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/python -m pip install -q -r requirements.txt
fi

echo "[backend] 在 http://localhost:${PORT} 启动（解析引擎见 /api/health）"
exec ./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT}"
