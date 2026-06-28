"""对话 Agent 的 **LangGraph 对照小样**（隔离 / 可选 / 不碰生产路径）。

这是一个刻意隔离的实验实现：把 `agent.run_turn` 那个手写的「`for range(_MAX_STEPS)`
工具循环 + `did_analyze` 布尔状态机」改用 LangGraph 的 `StateGraph` 表达，作为「手写版
vs 框架版」的对照样本（详见 docs/手写Agent编排_对照_LangGraph小样.md）。

设计原则——最大化复用、零侵入：
- **工具执行整体复用** `agent._dispatch_tool`：联网检索 / 匹配分析 / 生成计划 + 数据库
  持久化 + Task 物化 + 全部 SSE 事件（report/tool_call/tool_result/search_results/status）
  都不重写，只把它 yield 的事件经 LangGraph 的 custom 流转出、把工具结果文本包成 ToolMessage。
- **提示词 / 时间戳 / 冻结素材 / 语气 / 脚本化降级** 全复用 `agent.*` 现有纯函数。
- **工具 schema** 直接 `bind_tools(agent.TOOLS)`，与生产单一来源。
- **两步约束**（analyze 后同一轮不得直接 generate_plan）建模成图里一处 guard。

刻意**不做**（正是与生产手写版的取舍对照，不要在这里补）：
- 不做 block 级 prompt 缓存断点控制（生产 llm.py 的硬亮点，框架难干净表达，留在主路径）。
- 不做 token 用量的缓存命中统计落库（仅尽力产出 SSE usage 气泡，best-effort、不写库，
  避免用框架对象包裹后的不可靠数字污染 usage 统计）。
- 不做「协议而非厂商」的兼容网关兜底（去参重试 / 代理容错 / 6 档 effort 映射）。
- 语气直接并入系统提示（生产是「尾注置于缓存断点外」，此处简化）。

依赖（langgraph / langchain-*）**全部惰性导入**：本模块顶层只依赖标准库与 `. import`，
未安装实验依赖时导入本模块、启动主应用都不受影响；仅调用 run_turn 时才尝试导入，
缺失则优雅降级为一条提示。安装见 backend/requirements-lab.txt。

对外契约与 `agent.run_turn` 完全一致：run_turn(...) -> Iterator[Event]，事件元组
(类型, data) 同构，故可被 routers/chat_lab.py 用与 chat.py 相同的方式驱动。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy.orm import Session

from . import agent, llm

Event = tuple[str, dict]  # (事件类型, data)，与 agent.Event 同构

# 工具循环上限：每轮 agent→tools 为 2 个 superstep，16 足够 ~5-6 个工具回合（对照生产 _MAX_STEPS=5）。
_RECURSION_LIMIT = 16

# 两步约束被触发时回灌给模型的引导（对照生产 agent.py:316 的注入消息）。
_GATE_MSG = (
    "本轮请先向用户提出关键问题并【停下等待用户在新消息中回答】，"
    "不要在 analyze_match 的同一轮内生成学习计划。"
)

_MISSING_DEPS_MSG = (
    "LangGraph 对照小样未就绪：缺少实验依赖（{exc}）。\n"
    "这是一个【可选】实验端点，不影响主对话（/api/chat/stream）。\n"
    "如需体验，请在后端环境安装：pip install -r requirements-lab.txt"
)


# ---------------------------------------------------------------------------
# 惰性依赖与模型构造
# ---------------------------------------------------------------------------


def _check_deps(provider: str) -> None:
    """按生效 provider 校验实验依赖是否就绪（缺失抛 ImportError，供 run_turn 降级）。"""
    import langchain_core  # noqa: F401
    import langgraph  # noqa: F401

    if provider == "anthropic":
        import langchain_anthropic  # noqa: F401
    else:
        import langchain_openai  # noqa: F401


def _build_model(provider: str):
    """按生效 LLM 配置构造 LangChain 对话模型（复用 llm.py 的生效 provider/model/key/base_url）。

    注意：这里走的是 LangChain 的 ChatOpenAI/ChatAnthropic，**不复用** llm.py 的缓存断点与
    兼容兜底——这正是小样与生产手写版的取舍分界点。
    """
    api_key = llm._eff_api_key() or "not-needed"
    base_url = llm._eff_base_url() or None
    model_name = llm._eff_model()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name or "claude-sonnet-4-6",
            api_key=api_key,
            base_url=base_url,
            max_tokens=4096,
            streaming=True,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        streaming=True,
        stream_usage=True,  # 请求流末尾附带 usage（best-effort 命中统计用）
    )


# ---------------------------------------------------------------------------
# 消息构造（复用生产的时间戳 / 冻结素材 / 系统提示 / 语气逻辑）
# ---------------------------------------------------------------------------


def _initial_messages(messages: list[dict], context: dict, client_time: str) -> list:
    """把前端回传的对话历史转成 LangChain 消息序列。

    复用 agent 的纯函数：_system_prompt（恒定系统提示）、_tone_directive（语气）、
    _with_timestamp（每条消息时间前缀）、_user_content_with_materials（冻结素材快照）。
    与生产 run_turn 的历史构造逻辑一致，仅消息类型换成 LangChain 的 Message 对象。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    # 小样简化：语气并入系统提示（生产为缓存安全把它作为尾注置于断点外）。
    system = agent._system_prompt(context) + "\n\n" + agent._tone_directive(context.get("tone", 50))
    out: list = [SystemMessage(content=system)]

    history = [m for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    last_user = max((i for i, m in enumerate(history) if m.get("role") == "user"), default=-1)
    for i, m in enumerate(history):
        t = (m.get("time") or "").strip()
        if not t and i == last_user:
            t = (client_time or "").strip()
        if m["role"] == "user":
            content = agent._with_timestamp(agent._user_content_with_materials(m), t)
            out.append(HumanMessage(content=content))
        else:
            out.append(AIMessage(content=agent._with_timestamp(m.get("content", ""), t)))
    return out


def _chunk_text(chunk) -> str:
    """从 LangChain 流式 chunk 取出文本增量（content 可能为 str 或 content-block 列表）。"""
    c = getattr(chunk, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts)
    return ""


def _accumulate_usage(acc: dict, provider: str, usage_metadata: dict | None) -> None:
    """把 LangChain usage_metadata 尽力归一进累加器（best-effort，对照 usage.normalize_usage）。

    LangChain 的字段名与各 SDK 原始 usage 不同，缓存读写细节也未必齐全——这种「换框架后
    用量捕获要全部重接」正是小样不追平的取舍，故仅作 SSE 气泡展示、不落库。
    """
    if not usage_metadata:
        return
    details = usage_metadata.get("input_token_details") or {}
    hit = int(details.get("cache_read") or 0)
    in_tokens = int(usage_metadata.get("input_tokens") or 0)
    out_tokens = int(usage_metadata.get("output_tokens") or 0)
    if provider == "anthropic":
        # anthropic：input_tokens 不含缓存读写
        miss = in_tokens + int(details.get("cache_creation") or 0)
    else:
        # openai：input_tokens 含 cached
        miss = max(0, in_tokens - hit)
    acc["input_hit"] += hit
    acc["input_miss"] += miss
    acc["output"] += out_tokens
    acc["total"] += hit + miss + out_tokens


# ---------------------------------------------------------------------------
# 图构造：agent ⇄ tools 的 ReAct 循环 + 一处两步 guard
# ---------------------------------------------------------------------------


def _build_graph(context: dict, db: Session, user_id: str, provider: str, usage_acc: dict):
    """构造并编译本轮专用的 LangGraph 图（按请求闭包捕获 db/context/user_id，无 checkpointer）。

    图结构：
        START → agent → (有 tool_calls? → tools : END)
                tools → agent   （ReAct 回环；模型据工具结果继续说话/再调用，直到不再调用即 END）

    两步约束（analyze 后同一轮不得 generate_plan）= tools 节点里一处 guard：拦截即回灌
    引导消息并回到 agent，让模型自然地「提问后停下」——比生产手写循环里
    `布尔 + 注入 tool 消息 + stop_turn + break + if not spoke 兜底反问` 更干净。
    """
    from langchain_core.messages import ToolMessage
    from langgraph.config import get_stream_writer
    from langgraph.graph import END, START, MessagesState, StateGraph

    model_with_tools = _build_model(provider).bind_tools(agent.TOOLS)

    # 复用 LangGraph 内置 MessagesState（已含 messages + add_messages reducer），
    # 仅扩展一个跨节点累积位。用内置基类同时规避 `from __future__ import annotations`
    # 下函数内 TypedDict 前向引用无法被 get_type_hints 解析的问题。
    class LabState(MessagesState):
        did_analyze: bool  # 本轮是否已做过匹配分析

    # 注：内部节点/路由函数不标注 state 类型——`from __future__ import annotations` 下
    # 注解会变成字符串，而 LabState 是函数局部名，langgraph 推断 schema 时 get_type_hints 解析不到。
    def agent_node(state) -> dict:
        # 调用模型决策（说话 / 要工具）。stream_mode="messages" 会自动捕获其 token 增量。
        ai = model_with_tools.invoke(state["messages"])
        return {"messages": [ai]}

    def tools_node(state) -> dict:
        writer = get_stream_writer()  # 把 _dispatch_tool 的 SSE 事件经 custom 流转出
        last = state["messages"][-1]
        did = state.get("did_analyze", False)
        out: list = []
        for tc in last.tool_calls:
            name = tc["name"]
            tcid = tc["id"]
            args = tc.get("args") or {}

            # —— 两步约束 guard（对照生产 agent.py:310）——
            if name == "generate_plan" and did:
                out.append(ToolMessage(content=_GATE_MSG, tool_call_id=tcid))
                continue
            if name == "analyze_match":
                did = True

            # —— 整体复用生产工具执行：持久化 + 物化 + 全部 SSE 事件 ——
            sink: list[dict] = []  # 承接 _dispatch_tool 追加的 {"role":"tool","content":...}
            tool_dict = {"name": name, "id": tcid, "arguments": json.dumps(args, ensure_ascii=False)}
            for ev in agent._dispatch_tool(tool_dict, context, db, sink, user_id):
                writer({"sse": ev})
            content = sink[-1]["content"] if sink else f"（工具 {name} 无返回）"
            out.append(ToolMessage(content=content, tool_call_id=tcid))

        return {"messages": out, "did_analyze": did}

    def route_after_agent(state):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    g = StateGraph(LabState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


# ---------------------------------------------------------------------------
# 入口：与 agent.run_turn 同构的 SSE 生成器
# ---------------------------------------------------------------------------


def run_turn(
    messages: list[dict],
    context: dict,
    db: Session,
    reasoning_effort: str = "medium",
    client_time: str = "",
    user_id: str = "local",
) -> Iterator[Event]:
    """运行一轮对话（LangGraph 小样版），产出与 agent.run_turn 同构的 SSE 事件流。"""
    # 1) 降级：未启用 LLM 时复用生产的脚本化流程（与 /api/chat/stream 行为一致）。
    if not llm.streaming_supported():
        yield from agent._scripted_turn(context, db, user_id)
        return

    provider = llm._eff_provider()

    # 2) 实验依赖缺失：优雅提示，绝不 500、绝不影响主路径。
    try:
        _check_deps(provider)
    except ImportError as exc:
        yield ("delta", {"text": _MISSING_DEPS_MSG.format(exc=exc)})
        yield ("done", {})
        return

    usage_acc = {"input_hit": 0, "input_miss": 0, "output": 0, "total": 0}
    try:
        graph = _build_graph(context, db, user_id, provider, usage_acc)
        init: dict = {
            "messages": _initial_messages(messages, context, client_time),
            "did_analyze": False,
        }
        # 多模式流：custom=工具的 SSE 事件；messages=模型 token 增量；按执行顺序交错产出。
        for mode, chunk in graph.stream(
            init,
            stream_mode=["custom", "messages", "updates"],
            config={"recursion_limit": _RECURSION_LIMIT},
        ):
            if mode == "custom":
                ev = chunk.get("sse") if isinstance(chunk, dict) else None
                if ev:
                    yield ev
            elif mode == "messages":
                msg_chunk, _meta = chunk
                text = _chunk_text(msg_chunk)
                if text:
                    yield ("delta", {"text": text})
                _accumulate_usage(usage_acc, provider, getattr(msg_chunk, "usage_metadata", None))
    except Exception as exc:  # noqa: BLE001 兜底，避免流中断后前端无提示
        yield ("error", {"message": f"对话生成失败（LangGraph 小样）：{exc}"})
        return

    # best-effort 用量气泡（仅展示、不落库；对照说明见模块 docstring）。
    if usage_acc["total"] > 0:
        yield (
            "usage",
            {k: usage_acc[k] for k in ("input_hit", "input_miss", "output", "total")},
        )

    yield ("done", {})
