# 修改日志 · 2026-06-15（LangGraph 对照小样：隔离、可选、不碰生产）

在不动生产对话路径的前提下，新增一个用 **LangGraph** 重新实现同一套 Agent 编排的隔离小样，
作为「手写轻量编排 vs 框架编排」的对照样本与能力证明。完整对照见
《手写Agent编排_对照_LangGraph小样.md》。

## 修改内容

**新增（4 个文件）**
- `backend/app/services/agent_langgraph.py`：LangGraph 版 `run_turn`，对外契约与 `agent.run_turn`
  完全同构（`Iterator[Event]`）。核心：
  - `_build_graph`：`StateGraph`（继承内置 `MessagesState` + 扩展 `did_analyze`），
    `agent ⇄ tools` 的 ReAct 回环；条件边 `agent→tools/END`，`tools→agent`。
  - `tools_node` **整体复用** `agent._dispatch_tool`：把它 yield 的 SSE 事件经 LangGraph
    `get_stream_writer()` 的 `custom` 流转出、把工具结果文本包成 `ToolMessage`。零重写工具逻辑、
    持久化、物化。
  - 两步约束（analyze 后同轮不得 generate_plan）收敛成 tools_node 里**一处 guard**（回灌
    `_GATE_MSG` 并回到 agent，让模型自然「提问后停下」），替代生产版散落 3 处的
    `布尔 + 注入 + stop_turn + if not spoke 兜底`。
  - 复用生产纯函数：`_system_prompt / _tone_directive / _with_timestamp /
    _user_content_with_materials / _scripted_turn`；工具 schema 直接 `bind_tools(agent.TOOLS)`。
  - `run_turn` 用 `graph.stream(stream_mode=["custom","messages","updates"])`：`custom`→工具 SSE、
    `messages`→delta，按执行顺序交错翻译成 SSE 事件元组；末尾 best-effort `usage` 气泡 + `done`。
- `backend/app/routers/chat_lab.py`：`POST /api/chat/stream_lab`，镜像 `chat.py` 的专属
  contextvars context 驱动（override + 用量归属 path=chat），仅把 `agent.run_turn` 换成
  `agent_langgraph.run_turn`。
- `backend/requirements-lab.txt`：可选实验依赖（langgraph + langchain-core/-openai/-anthropic），
  标注非运行 MVP 必需。
- `docs/手写Agent编排_对照_LangGraph小样.md`：对照笔记（结构图、复用清单、取舍表、跑法、验证记录）。

**仅改 2 行**
- `backend/app/main.py`：`from .routers import (... chat_lab ...)` + `app.include_router(chat_lab.router)`。

**隔离保证**：langgraph/langchain 在 `agent_langgraph.py` 内**全部惰性导入**（函数内），顶层零依赖；
未安装实验依赖时 `import app.main`、应用启动、现有端点均不受影响，新端点优雅降级为一条提示。

## 原因

- **堵叙事裂缝**：本产品把 LangChain/LangGraph 列为 AI Agent 岗位核心技能（`data/skills.py:162`、
  `agent.py:205`），却在自己最该用的地方手写绕开。小样提供一个 repo 里真能跑的 LangGraph 工件。
- **工程故事**：同时拥有手写版与框架版，可讲清「会用框架」+「为什么生产不用它」（缓存/兼容/用量
  绑定的取舍），比一边倒更资深。
- **为未来探针**：项目的根因短板是「长期状态地基」；LangGraph 的 checkpointer/Store 正对这块。
  小样先把编排迁通，验证「框架能否干净承接缓存控制」这条技术否决项，为是否全量迁移积累硬证据。

## 抉择

- **只引 LangGraph 内核、不换 `llm.py`**：明确**不**用 LangChain 统一 LLM 调用——`llm.py` 的协议封装
  与兼容兜底优于框架默认路径，换它是净损失。小样走 LangChain ChatModel 仅为「框架版」的完整性，
  且正是缓存/兼容取舍的分界点。
- **隔离而非重构**：新文件 + 端点 + 惰性导入，生产 `agent.py`/`llm.py`/现有 137 测试一行未改、全绿。
  对照决策（见对话记录）结论是「现在全量迁移不划算」，故只做隔离小样。
- **复用而非重写**：tools_node 直接调 `agent._dispatch_tool`，工具执行/持久化/物化/SSE 事件单一来源，
  避免两套实现漂移；小样只「拥有」编排（图）与模型调用。
- **缓存/用量刻意不追平**：小样不做 block 级缓存断点、不把 chat 级用量落库（仅 SSE 气泡 best-effort），
  避免用框架对象包裹后的不可靠数字污染 usage 统计——这正是与生产手写版的取舍对照，不在小样补。
- **状态模型**：用 `MessagesState` 子类规避 `from __future__ import annotations` 下函数内 TypedDict
  前向引用无法被 `get_type_hints` 解析的问题；内部节点/路由函数不标注 `state` 类型（同因）。
- **stateless-per-turn**：小样不引 checkpointer，保持与现有「前端整段回传历史」的无状态每轮模型一致，
  使其成为前端可原样切换的 drop-in；checkpointer 留作「长期状态地基」专项时再上（对照笔记已标钩子位）。

## 验证

无需真实 LLM/网络/DB 的结构化 + 假模型（`GenericFakeChatModel`/`graph.invoke`）验证：未装 langgraph
时 app 照常导入；无 LLM 降级；图在 openai/anthropic 两路径编译成功且结构正确；`bind_tools(agent.TOOLS)`
通过；`_initial_messages` 复用生产逻辑正确；custom→SSE 与 messages→delta 往返；工具路径端到端
（`agent→tools(web_search)→agent→END`）；两步 guard 拦截 generate_plan。后端 **137 passed**（零回归）。
未做真实 provider 在线流式跑（需真 key/产生费用），留待手动连真实 LLM 确认。
