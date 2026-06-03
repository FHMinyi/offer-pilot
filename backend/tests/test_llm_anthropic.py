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


def test_system_prompt_injects_time():
    ctx = {"resume_text": "", "jd_texts": [], "target_role": "前端实习", "weeks": 4}
    prompt = agent._system_prompt(ctx, client_time="2026-06-02 10:30:00 CST")
    assert "2026-06-02 10:30:00 CST" in prompt
    assert "当前时间" in prompt
    # 无传入时回退服务器时间（不为空）
    prompt2 = agent._system_prompt(ctx, client_time="")
    assert "当前时间" in prompt2
