# 手写 Agent 编排 vs LangGraph 对照小样

> 一份「同一件事、两种实现」的工程对照笔记。
> 生产路径 = 手写轻量编排（`services/agent.py` + `services/llm.py`）；
> 对照小样 = 隔离的 LangGraph 实现（`services/agent_langgraph.py`，端点 `POST /api/chat/stream_lab`）。

## 为什么有这份东西

OfferPilot 的技能库把 **LangChain / LangGraph** 列为「AI Agent 岗位的核心技能」、还在系统提示里
举它为例提醒模型别漏（`data/skills.py:162`、`agent.py:205`）。一个「教别人去学 LangGraph 才能拿
offer」的项目，自己却在最该用的地方手写循环绕开它——这是叙事裂缝。

但生产路径**故意不迁** LangGraph，因为手写版承载了项目真正的工程亮点（block 级 prompt 缓存控制、
「协议而非厂商」的兼容性、与 usage 命中统计的深度绑定），而 LangGraph 难干净承接这些（见下表）。

于是有了这个**隔离的、可选的对照小样**：在不动生产路径的前提下，用 LangGraph 把同一套 Agent 编排
再实现一遍。它同时回答了两个问题——「会不会用主流框架？」（会，这就是证据）和「为什么生产不用它？」
（因为下表的取舍）。**能同时讲清这两点，比一边倒更资深。**

## 两种实现的结构对照

同一套业务：一轮对话里，助手可说话、按需调用 `web_search` / `analyze_match`（第一步）/
`generate_plan`（第二步），且**两步约束**——`analyze_match` 之后必须先反问、停下等用户，不得在同一轮直接出计划。

### 生产手写版（`agent.run_turn`）

```
for _ in range(_MAX_STEPS):              # 手写工具循环
    for ev in llm.agent_stream(...):     # 逐事件：reasoning/delta/tool_pending/final
        ...
    if final.finish == "tool_calls":
        append assistant tool_calls
        for t in tool_calls:
            if t == generate_plan and did_analyze:   # 两步约束 = 布尔 + 注入消息 + stop_turn + break
                inject "先反问并停下"; stop_turn = True; continue
            if t == analyze_match: did_analyze = True
            _dispatch_tool(t, ...)        # 执行 + 回灌 tool 结果
        if stop_turn:
            if not spoke: inject 兜底反问  # 模型没说话时补问
            break
```
两步约束散落在 **3 处**：系统提示的自然语言（`agent.py:201-217`）+ `did_analyze` 布尔 +
循环里的 `stop_turn`/`if not spoke` 硬编码（`agent.py:306-342`）。

### LangGraph 小样版（`agent_langgraph._build_graph`）

```
        ┌─────────────────────────────────────────┐
        ▼                                           │
   START → agent ──(有 tool_calls?)──► tools ───────┘   （ReAct 回环）
              │
              └──(无 tool_calls)──► END

   tools 节点内一处 guard：
     if name == "generate_plan" and did_analyze:
         回灌 _GATE_MSG（"先反问并停下"）→ 不执行 → 回到 agent
     模型据引导自然地「提问后停下」→ 下一轮 agent 无工具调用 → END
```
两步约束收敛成 **1 处** guard（`agent_langgraph.py` tools_node）。模型被引导后自己提问、自己停，
不需要生产版的 `if not spoke` 兜底反问——这是图结构带来的、更干净的一点。

## 复用了什么 / 新写了什么

小样的设计原则是**最大化复用、零侵入**：

| 复用生产代码（未改一行） | 小样新增 |
|---|---|
| `agent._dispatch_tool`：联网/分析/计划 + DB 持久化 + Task 物化 + **全部 SSE 事件** | `StateGraph`：agent ⇄ tools 的 ReAct 图 |
| `agent.TOOLS`：工具 schema（`bind_tools(agent.TOOLS)` 直接吃 openai 格式 dict） | 把 `_dispatch_tool` 的事件经 LangGraph `custom` 流转出、结果包成 `ToolMessage` |
| `agent._system_prompt / _tone_directive / _with_timestamp / _user_content_with_materials` | 多模式流（`custom`+`messages`）→ SSE 事件元组的翻译 |
| `agent._scripted_turn`：无 LLM 时的脚本化降级 | 两步约束 guard（1 处） |
| `llm._eff_provider/_eff_model/_eff_api_key/_eff_base_url`：生效配置 | best-effort usage 归一 |

对外契约（`run_turn(...) -> Iterator[Event]`，事件元组同构）与生产一致，故 `routers/chat_lab.py`
能用与 `chat.py` **完全相同**的方式驱动它（专属 contextvars context + `ctx.run(next, inner)`）。

## 核心取舍（小样**刻意不做**的，正是生产手写版的价值所在）

| 维度 | 生产手写版 | LangGraph 小样 |
|---|---|---|
| **Prompt 缓存** | block 级 `cache_control` 断点（system 末尾 + 最后一条消息末块）、语气尾注置于断点外、素材冻结进历史（`llm.py:486`、`agent.py:162-188`） | 不做。走 LangChain ChatModel，框架对 anthropic ephemeral 断点位置控制力有限，迁移需绕过框架手塞——故留在生产 |
| **Provider 兼容** | 「协议而非厂商」+ 多处「不认参数就去掉重试」（`reasoning_effort`/`stream_options`/`cache_control`/`thinking`）+ 代理容错 + 6 档 effort 映射 | 不做。仅按生效配置构造 ChatOpenAI/ChatAnthropic |
| **Usage 命中统计** | 直读各 SDK 原始 `cached_tokens`/`cache_read_input_tokens`，归一落库 + SSE 气泡，与缓存绑定（`usage.py`） | 仅 best-effort SSE 气泡、**不落库**（LangChain `usage_metadata` 字段不同、缓存细节未必齐全，避免污染统计）。注：小样内 `analyze_match` 触发的解析用量仍照常归属落库 |
| **语气** | 尾注置于缓存断点外，改语气不冲历史前缀 | 简化：并入系统提示 |
| **控制流可读性** | 直白同步生成器 + 显式 contextvars，可逐行讲；但两步约束散落 3 处 | 显式状态图，可画图；两步约束收敛 1 处 |
| **依赖** | 运行 MVP **零 LLM 框架依赖**（连 openai/anthropic 都是注释掉的可选包） | 需 `requirements-lab.txt`（langgraph + langchain-*） |

**一句话结论**：LangGraph 在「编排可读性 / 状态图可视化 / 两步约束的表达」上更优；手写版在
「缓存的精细控制 / 兼容性 / 与用量统计的绑定 / 零依赖可演示」上更优。生产保留手写版，小样作为
能力证明与未来若做「长期状态地基（checkpointer/Store）」时的探针。

## 隔离性保证（怎么做到「不碰生产」）

- 新增文件：`services/agent_langgraph.py`、`routers/chat_lab.py`、`requirements-lab.txt`。
- 仅改 `main.py` 两行（import + `include_router`）注册端点。
- **langgraph/langchain 全部惰性导入**（在函数内）：未安装实验依赖时，`import app.main` 与应用启动
  **完全不受影响**，该端点优雅降级为一条提示。
- 生产端点 `/api/chat/stream`、`agent.py`、`llm.py`、现有 137 个测试**一行未改、全绿**。

## 怎么跑

```bash
# 1) 安装可选实验依赖（走 openai 协议只需 langchain-openai；anthropic 同理）
cd backend && pip install -r requirements-lab.txt

# 2) 配置任一 LLM（与主对话共用 .env / 或前端 BYO key 覆盖），然后请求新端点：
curl -N -X POST http://127.0.0.1:8000/api/chat/stream_lab \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"帮我看看 AI Agent 岗位的匹配度","time":"2026-06-15 10:00"}],
       "context":{"target_role":"AI Agent 开发","resume_text":"...","jd_texts":["..."],"weeks":4},
       "client_time":"2026-06-15 10:00"}'
```
返回的 SSE 事件（`status/delta/tool_call/tool_result/report/usage/done`）与 `/api/chat/stream`
**同构**，前端可原样切换两个端点做对照。未配置 LLM 时两端点都走脚本化规则降级。

## 验证记录（2026-06-15）

无需真实 LLM/网络/DB 的结构化 + 假模型驱动验证（`GenericFakeChatModel` / `graph.invoke`）：

- ✅ 未装 langgraph 时 `import app.main` 成功、应用照常启动（隔离铁律）
- ✅ 未启用 LLM 时 `run_turn` 走脚本化降级
- ✅ 实验依赖安装并导入（langgraph 1.2.5 / langchain-core 1.4.7 / -openai 1.3.2 / -anthropic 1.4.6）
- ✅ 图在 openai / anthropic 两路径均编译成功，结构正确（`agent` 条件分叉到 `tools`/`END`，`tools→agent`）
- ✅ `bind_tools(agent.TOOLS)` 接受 openai 格式工具 dict
- ✅ `_initial_messages` 正确复用生产的时间前缀 / 冻结素材 / 恒定系统提示 / 语气
- ✅ custom writer → SSE 往返、messages 模式 → delta 翻译（微测）
- ✅ 工具路径端到端：`agent→tools(web_search 经 _dispatch_tool)→agent→END`，消息链
  `Human→AI(工具调用)→Tool(结果)→AI(反问)`
- ✅ 两步 guard：`analyze` 后同轮 `generate_plan` 被拦截、回灌引导、未执行
- ✅ 现有后端测试 **137 passed**（零回归）
- ⏳ **未做**：真实 provider 的在线流式跑（需真 key、产生费用）——这正是「对外部真值的验证」那一步，
  留待手动连真实 LLM 时确认 token 流与缓存表现。

## 何时考虑「全量迁移」（而非仅留小样）

满足任一即可重新评估（详见对话决策记录）：
1. 目标从「作品集/演示」转向多用户商业上线（需可中断恢复/断点续跑/并发隔离）；
2. 工具/步骤显著膨胀（3 工具 1 布尔 → 8+ 工具多分支），手写派发可维护性崩塌；
3. 把「展示主流框架工程能力」设为作品集首要叙事；
4. （技术否决项）验证 LangGraph 能干净表达 block 级 ephemeral 缓存断点 + 与 usage 命中统计绑定——
   只要这条不成立，即便 1-3 满足，也应「框架做编排/记忆、缓存与 usage 仍走手写旁路」的混合方案。
