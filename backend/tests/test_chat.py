"""对话 /api/chat/stream 的测试（规则/脚本化降级路径，LLM_PROVIDER=none）。

测试环境未配置 LLM，Agent 走脚本化流程：缺料时索取，齐全时跑规则分析并出报告。
同时校验 SSE 帧格式。
"""

from __future__ import annotations

import json

from .sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析为 [(event, data_dict)]。"""
    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        event, data = None, None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if event is not None:
            events.append((event, data or {}))
    return events


def test_chat_asks_for_resume_when_empty(client):
    r = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "你好"}], "context": {}},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    types = [e for e, _ in events]
    assert "delta" in types and "done" in types
    # 应提示补充简历
    text = "".join(d.get("text", "") for e, d in events if e == "delta")
    assert "简历" in text


def test_chat_runs_analysis_and_streams_report(client):
    payload = {
        "messages": [{"role": "user", "content": "请基于我提供的简历和 JD 分析"}],
        "context": {
            "resume_text": SAMPLE_RESUME,
            "jd_texts": SAMPLE_JDS,
            "target_role": "前端实习",
            "weeks": 3,
        },
    }
    r = client.post("/api/chat/stream", json=payload)
    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [e for e, _ in events]

    assert "report" in types, f"应产出报告，实际事件：{types}"
    assert types[-1] == "done"

    report = next(d for e, d in events if e == "report")
    assert report["analysis_run_id"] > 0
    result = report["result"]
    assert 0 <= result["match_score"] <= 100
    assert len(result["roadmap"]) == 3
    assert result["skill_gap"]["must_have_gaps"]

    # 报告应已持久化，可在历史中查到
    hist = client.get("/api/analysis").json()
    assert any(s["id"] == report["analysis_run_id"] for s in hist)
