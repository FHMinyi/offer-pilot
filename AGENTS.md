# AGENTS.md

## 语言规则

所有交互、注释生成、代码解释、文档编写以及记忆存储中，始终使用简体中文（zh-CN）。

## 项目定位

OfferPilot 是面向应届生和实习求职在校生的 AI 求职规划工具。

当前优先解决：

- 学生简历、项目经历与实习/校招 JD 的匹配
- 技能缺口分析
- 项目与简历表达优化
- 面向实习/校招的学习路线和面试准备

## 目标用户

主目标用户：

- 应届生
- 想找实习的大二、大三、大四在校生
- 有课程项目、个人项目、比赛经历或开源经历，但不知道如何匹配岗位要求的学生

次级用户：

- 0~1 年经验的初级求职者
- 转行到技术岗位的人
- 想系统整理自身能力的人

## 技术栈约定

MVP 阶段优先使用：

- 前端：Vue 3 + Vite + TypeScript
- 后端：FastAPI
- 数据库：PostgreSQL
- 工作流：先使用可控的轻量 Workflow，后续再引入 LangGraph
- 爬虫：Playwright 作为后续能力，MVP 不优先依赖
- 向量库：可选，MVP 不强依赖

## 开发原则

- 优先围绕 MVP 闭环推进，不要过早扩展到自动投递、复杂爬虫、大规模 Agent 自治、MCP 或 Skill。
- 先保证简历/JD 解析、技能缺口分析、项目表达优化和学习路线生成的结果可信。
- 能用结构化规则和清晰工作流解决的问题，先不要引入复杂 Agent 编排。
- 涉及产品定位、技术选型、目标用户或 MVP 范围的变更，应同步更新 `docs/` 下的规划文档。
- 代码、注释和文档应尽量保持简洁、可维护，避免无必要的抽象。

## 提交规范

提交信息使用以下格式：

```text
<type>(<scope>): <summary>

<正文：描述本次变更的背景与动机>

Agent-Task: <原始任务描述或任务 ID>
Agent-Model: <使用的模型，如 gpt-4o、gemini-2.5-pro>
Agent-Decision: <关键设计决策及理由>
Agent-Limitation: <已知局限或后续 TODO>
```

常用类型：

- `docs`：文档变更
- `feat`：新增功能
- `fix`：问题修复
- `chore`：工程配置或维护
- `refactor`：重构
- `test`：测试相关
<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
