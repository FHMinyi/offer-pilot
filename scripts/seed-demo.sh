#!/usr/bin/env bash
# 播种演示数据：为录制 demo / 截图准备一份「活」的状态（旅程 + 任务 + 打卡 + 再规划）。
# 复用后端虚拟环境与规则模式分析，零配置、不依赖 LLM/联网。
# 详见 backend/seed_demo.py 顶部说明。会清空 user_id='local' 的三张状态表，勿在生产库运行。
set -euo pipefail

cd "$(dirname "$0")/../backend"

if [ ! -d .venv ]; then
  echo "[seed] 未发现 backend/.venv，请先运行 ./scripts/dev-backend.sh 安装依赖。" >&2
  exit 1
fi

exec ./.venv/bin/python seed_demo.py
