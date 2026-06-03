#!/usr/bin/env bash
# 启动前端开发服务器（Vue 3 + Vite）。
# 首次运行会自动安装依赖。
# 若后端不在默认 8000 端口，用 VITE_API_TARGET 指定，例如：
#   VITE_API_TARGET=http://localhost:8010 ./scripts/dev-frontend.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}/frontend"

# 优先使用项目本地 Node（.tooling/node），否则回退系统 Node（需 18+）
if [ -x "${ROOT}/.tooling/node/bin/node" ]; then
  export PATH="${ROOT}/.tooling/node/bin:${PATH}"
fi

echo "[frontend] node $(node -v)"

if [ ! -d node_modules ]; then
  echo "[frontend] 安装依赖…"
  npm install --no-audit --no-fund
fi

echo "[frontend] 在 http://localhost:5173 启动"
exec npm run dev
