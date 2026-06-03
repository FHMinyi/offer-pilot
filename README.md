# OfferPilot

OfferPilot 是一个面向应届生和实习求职者的 AI 求职规划 Agent，目标是帮助用户基于简历、项目经历和目标岗位 JD，分析技能缺口、优化项目表达，并生成可执行的学习与面试准备路线。

## 当前阶段

已实现**流式对话式（LUI）求职规划 Agent**（v0.2）：

> 在对话框里上传简历、粘贴 JD、补充目标方向 → AI 边做边把过程与输出**流式**展示（可联网检索该岗位当前常见技能）→ 产出可解释的结构化报告（匹配度、技能缺口、简历优化、分周路线）→ 可继续追问、调整重跑、导出 Markdown、查看历史。

底层仍是可控的分析闭环（PRD Phase 1）：岗位画像 → 技能缺口（含来源说明）→ 简历/项目优化 → 按周学习/面试路线。

**两个亮点：**
- **过程可见**：分析以 SSE 流式输出，工具调用（联网搜索/运行分析）与 AI 解读实时呈现，不再「黑屏等待」。
- **可离线、可降级**：未配置 LLM 时后端自动用规则解析跑通闭环；未配置搜索时 Agent 仅凭已有知识作答。配置后自动增强。

## 快速开始

前置：Python 3.10+；Node 18+（仓库已在 `.tooling/` 放置本地 Node 24，脚本会自动优先使用）。

```bash
# 终端 1：后端（首次会自动建虚拟环境并装依赖）
./scripts/dev-backend.sh            # 默认 http://localhost:7968

# 终端 2：前端（首次会自动 npm install）
./scripts/dev-frontend.sh           # http://localhost:5173
```

打开 http://localhost:5173 ，粘贴简历与若干 JD，点击「开始分析」。

> 后端默认端口为 7968，可覆盖：
> `PORT=8010 ./scripts/dev-backend.sh` 启动后端，
> 同时 `VITE_API_TARGET=http://localhost:8010 ./scripts/dev-frontend.sh` 启动前端。

启用 LLM（可选）：复制 `backend/.env.example` 为 `backend/.env`，把 `LLM_PROVIDER` 设为 `openai` 或 `anthropic`（这里指 **API 协议**，不绑定厂商）。配合 `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` 可对接任意兼容服务（DeepSeek、OpenRouter、本地 vLLM/Ollama 等），对接兼容服务时需同时设置 `LLM_MODEL`。还需把对应 SDK 装进 venv：`pip install openai`（或 `anthropic`）。详见 `backend/.env.example`。

启用联网搜索（可选）：在 `backend/.env` 设置 `TAVILY_API_KEY`，让 Agent 能检索较新岗位的常见技能（如 AI Agent 方向的 LangChain/RAG 等）。后端走你环境里现有的 HTTP 代理出网，不会修改任何代理环境变量。

## 项目结构

```
backend/        FastAPI 后端
  app/
    services/   核心分析工作流：简历解析 / JD 解析 / 技能归一化 / 缺口分析 / 优化建议 / 路线生成 / LLM 抽象 / pipeline 编排
    routers/    API 路由
    data/       技能本体 v0.1（别名表 + 树 + 学习模板）
    models.py   ORM（Resume / JobPosting / AnalysisRun）
  tests/        pytest（规则模式下的离线端到端测试）
frontend/       Vue 3 + Vite + TypeScript 前端
  src/views/    新建分析 / 结果页 / 历史记录
scripts/        一键启动脚本
docs/           PRD、项目整理与实现说明
```

## 核心 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/stream` | **对话式 Agent（SSE 流式）**：流式输出 + 工具调用（联网搜索/运行分析）+ 报告 |
| POST | `/api/analysis/run` | 运行一次完整分析（结构化，对话 Agent 内部也复用它） |
| GET | `/api/analysis` | 历史记录列表 |
| GET | `/api/analysis/{id}` | 单次分析完整结果 |
| POST | `/api/resumes/upload` | 上传 PDF 简历，抽取文本 |
| POST | `/api/resumes/parse` | 粘贴文本解析简历 |
| POST | `/api/jobs/import` | 批量导入 JD |
| GET | `/api/skills/graph` | 技能图谱 |
| GET | `/api/health` | 健康检查（含当前解析引擎） |

启动后端后，交互式文档见 http://localhost:7968/docs 。

## 测试

```bash
cd backend && . .venv/bin/activate && pytest
```

## 目标用户

- 应届生
- 想找实习的大二、大三、大四在校生
- 有课程项目、个人项目或比赛经历，但不知道如何匹配岗位要求的学生

## 技术栈

- 前端：Vue 3 + Vite + TypeScript
- 后端：FastAPI
- 数据库：SQLite（MVP 默认，零配置）/ PostgreSQL（通过 `DATABASE_URL` 切换）
- 工作流：轻量可控 Workflow（后续考虑 LangGraph）
- LLM：OpenAI / Anthropic 兼容协议（对话式 Agent 需模型支持 function calling；可选，缺省走规则解析）
- 联网搜索：Tavily（可选，用于补齐较新岗位的常见技能；缺省不联网）
- 对话：SSE 流式 + 可控工具调用（web_search / run_analysis）

## 文档

- [项目整理](./docs/AI求职Agent项目（OfferPilot）整理.md)
- [PRD 与技术方案草案](./docs/OfferPilot_PRD_技术方案草案.md)
- [MVP 实现说明 v0.1](./docs/实现说明_v0.1.md)

## License

AGPL-3.0
