"""思考强度映射、openai↔anthropic 消息/工具转换、时间注入的单元测试（纯逻辑，无网络）。"""

from __future__ import annotations

from app.services import agent, llm


def test_openai_effort_mapping():
    assert llm._OPENAI_EFFORT["off"] is None
    assert llm._OPENAI_EFFORT["low"] == "low"
    assert llm._OPENAI_EFFORT["medium"] == "medium"
    assert llm._OPENAI_EFFORT["high"] == "high"
    # 6 档：xhigh/max 截到 API 上限 high
    assert llm._OPENAI_EFFORT["xhigh"] == "high"
    assert llm._OPENAI_EFFORT["max"] == "high"


def test_anthropic_budget_mapping():
    b = llm._ANTHROPIC_BUDGET
    assert b["off"] == 0
    # 单调递增，max 最大
    vals = [b["low"], b["medium"], b["high"], b["xhigh"], b["max"]]
    assert vals == sorted(vals) and len(set(vals)) == len(vals)
    assert b["max"] == max(vals)


def test_tools_to_anthropic():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "搜索",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]
    out = llm._tools_to_anthropic(tools)
    assert out[0]["name"] == "web_search"
    assert out[0]["description"] == "搜索"
    assert out[0]["input_schema"]["properties"]["query"]["type"] == "string"


def test_messages_to_anthropic_conversion():
    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "分析"},
        {
            "role": "assistant",
            "content": "好的",
            "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "run_analysis", "arguments": '{"weeks": 4}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "匹配度 60%"},
    ]
    system, conv = llm._messages_to_anthropic(messages)

    assert system == "你是助手"
    # user / assistant / user(tool_result)
    assert [m["role"] for m in conv] == ["user", "assistant", "user"]

    # assistant：文本 + tool_use
    a = conv[1]["content"]
    assert a[0] == {"type": "text", "text": "好的"}
    assert a[1]["type"] == "tool_use"
    assert a[1]["id"] == "t1" and a[1]["name"] == "run_analysis"
    assert a[1]["input"] == {"weeks": 4}

    # tool -> user 的 tool_result
    tr = conv[2]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "t1"
    assert tr["content"] == "匹配度 60%"


def test_messages_to_anthropic_merges_consecutive_same_role():
    # 连续两条 tool 结果应合并进同一个 user 消息（满足交替约束）
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": "ra"},
        {"role": "tool", "tool_call_id": "b", "content": "rb"},
    ]
    _system, conv = llm._messages_to_anthropic(messages)
    assert [m["role"] for m in conv] == ["user", "assistant", "user"]
    # 两条 tool_result 合并
    assert len(conv[2]["content"]) == 2
    assert {b["tool_use_id"] for b in conv[2]["content"]} == {"a", "b"}


def test_system_prompt_time_convention_is_stable():
    # 时间改为每条消息自带，系统提示只留稳定约定说明、无具体时间值（缓存评审：每条消息自带时间）
    ctx = {"resume_text": "", "jd_texts": [], "target_role": "前端实习", "weeks": 4}
    prompt = agent._system_prompt(ctx)
    assert "【时间】" in prompt
    assert "以最新一条用户消息的时间为" in prompt
    # 不再注入任何具体时间值
    assert "当前时间：" not in prompt


def test_system_prompt_fully_stable():
    """缓存评审：时间与语气都已移出系统提示 → 不同 tone / 不同时刻调用都字节级一致。"""
    base = {"resume_text": "张三的简历", "jd_texts": ["某 JD 全文"], "target_role": "前端", "weeks": 4}
    p1 = agent._system_prompt({**base, "tone": 0})
    p2 = agent._system_prompt({**base, "tone": 100})
    assert p1 == p2
    # 系统提示不含具体时间值、不含语气
    assert "当前时间：" not in p1 and "语气强度" not in p1
    # 材料置于末尾（仅中途新增素材才变），前缀其余部分恒定
    assert p1.rstrip().endswith("某 JD 全文")


def test_with_timestamp_prefix():
    # 有 time → 加【时间】前缀；空/空白 → 原样
    assert agent._with_timestamp("你好", "2026/06/13 14:03") == "【2026/06/13 14:03】你好"
    assert agent._with_timestamp("你好", "") == "你好"
    assert agent._with_timestamp("你好", "   ") == "你好"


def test_tone_tail_note_stays_outside_cache_prefix():
    # 模拟 anthropic_stream 的顺序：先打断点（落在真实用户块），再追加语气尾注块（无断点）
    conv = [{"role": "user", "content": [{"type": "text", "text": "【t】hi"}]}]
    kwargs = {"system": "S", "messages": conv}
    llm._add_cache_breakpoints(kwargs)
    real_block = conv[-1]["content"][-1]
    assert real_block["cache_control"] == {"type": "ephemeral"}  # 断点在真实用户块
    conv[-1]["content"].append({"type": "text", "text": "语气尾注"})  # 尾注后追加
    assert "cache_control" not in conv[-1]["content"][-1]  # 尾注不带断点 → 在缓存前缀之外
    assert conv[-1]["content"][-2] is real_block  # 真实块仍是被缓存的最后一块


def test_anthropic_cache_breakpoints_add_and_strip():
    kwargs = {
        "system": "你是助手",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "你好"}]},
        ],
    }
    llm._add_cache_breakpoints(kwargs)
    # system 转 block 列表并带断点；最后一条消息的最后一个 block 带断点；其余不带
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kwargs["messages"][0]["content"][0]
    # 兼容网关不认时可完整剥离还原
    assert llm._strip_cache_breakpoints(kwargs) is True
    assert kwargs["system"] == "你是助手"
    assert "cache_control" not in kwargs["messages"][-1]["content"][-1]
    assert llm._strip_cache_breakpoints(kwargs) is False
