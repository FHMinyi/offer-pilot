# AI 求职 Agent 项目（OfferPilot）完整整理

> 这是一版概要总纲；更细的 PRD 与技术方案草案见 `docs/OfferPilot_PRD_技术方案草案.md`

---

# 一、项目核心想法

构建一个 **AI 求职与学习规划 Agent 系统**，从用户的：

- 简历
- 目标岗位

出发，自动完成：

- 岗位需求分析（JD Mining）
- 技能缺口分析（Skill Gap Analysis）
- 学习路线生成（Roadmap Generation）
- 面试准备辅助（Interview Simulation，可扩展）

### 核心目标

> 帮助用户更快拿到 Offer，而不是单纯“学知识”。

### 首发目标用户

优先面向 **应届生、想找实习的大二/大三/大四在校生**，先解决在校生从“课程/项目经历”到“实习/校招岗位要求”的匹配、补强和表达问题。

---

# 二、产品形态选择（关键决策）

## ❌ 不推荐

- 只做 Skill（Prompt能力封装）
- 只做 MCP Server（协议层，无产品感）

---

## ✔ 推荐主形态

- Web App（核心产品形态）
- Agent Workflow（核心能力）

---

## ✔ 可扩展形态

- CLI（开发者工具）
- MCP Server（能力开放接口）
- Skill（Prompt资产沉淀）

---

# 三、MVP版本（最小可行产品）

## 功能

- 上传简历（PDF解析）
- 输入目标实习/校招岗位
- 抓取/输入 JD（MVP 先 3~10 个，后续扩展到 50~100 个）
- 生成技能缺口分析
- 生成简历/项目优化建议
- 生成学习与面试准备路线（按周拆分）

---

## 输出示例

```

匹配度：72%

缺失技能：

* TypeScript
* Docker
* Node.js

学习路线：
Week1: TypeScript
Week2: Vue3
Week3: Vite
Week4: Docker

```

---

# 四、系统架构（Agent设计）

```

User Input
↓
Resume Parser Agent
↓
Job JD Collector Agent
↓
Skill Gap Analysis Agent
↓
Roadmap Generation Agent
↓
Result Output

```

---

## 技术栈建议

- Frontend: Next.js + React
- Backend: FastAPI
- LLM: OpenAI / Claude
- Workflow: LangGraph
- DB: PostgreSQL
- Vector DB: Qdrant（可选）
- Crawler: Playwright

---

# 五、能力层拆解（核心价值）

## 1. JD分析

- 显式技能提取
- 隐式技能推断

---

## 2. 技能图谱

```

前端
├── HTML
├── CSS
├── JavaScript
│    ├── ES6
│    ├── Event Loop
│    └── 闭包
├── Vue
│    ├── 响应式
│    ├── Diff
│    └── Router

```

---

## 3. 熟练度体系

- 了解（知道概念）
- 熟悉（能使用）
- 掌握（理解原理）
- 精通（能优化/解决复杂问题）

---

# 六、产品进化路径

## Phase 1（MVP）

- Web App
- 简历 + JD分析
- 学习路线生成

---

## Phase 2

- 引入 LangGraph Agent
- 模块化拆分 Agent

---

## Phase 3

- CLI工具
- 开发者体验增强

---

## Phase 4

- MCP Server（能力开放）

---

## Phase 5

- Skill沉淀（Prompt资产）

---

# 七、MCP / CLI / Skill 的客观定位

## CLI（推荐）

- ✔ 最容易展示工程能力
- ✔ 适合开源
- ✔ 面试友好

---

## MCP

- ✔ 基础设施能力
- ✔ 可作为“能力接口层”
- ❌ 不适合当主项目

---

## Skill

- ✔ Prompt资产沉淀
- ✔ 可作为附加模块
- ❌ 单独做工程价值弱

---

# 八、面试官视角评价

| 项目类型 | 评分 |
|----------|------|
| MCP-only | 6/10 |
| Agent Web App | 8/10 |
| Web + Agent + MCP | 9/10 |

---

## 面试官关注点

- 是否有真实产品形态
- 是否体现 Agent workflow
- 是否有工程复杂度
- 是否可扩展

---

# 九、最终推荐路线（最重要）

```

第一步：做 Web Agent 产品（OfferPilot）
第二步：补 CLI（增强工程感）
第三步：可选 MCP（开放能力）
第四步：Skill（沉淀方法论）

```

---

# 十、一句话总结

> 做一个“能帮人找到工作”的 AI Agent 产品，而不是“做 Agent 技术本身”。

---
