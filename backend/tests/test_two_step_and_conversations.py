"""两步分析（匹配/路线分离 + 偏好）与会话持久化的测试（规则模式）。"""

from __future__ import annotations

from app.services import pipeline

from .sample_data import SAMPLE_JDS, SAMPLE_RESUME


def test_analyze_match_streaming_has_no_roadmap():
    statuses = []
    outcome = None
    for kind, payload in pipeline.analyze_match_streaming(SAMPLE_RESUME, SAMPLE_JDS[:2], "前端实习"):
        if kind == "status":
            statuses.append(payload)
        elif kind == "result":
            outcome = payload

    assert outcome is not None
    result = outcome["result"]
    # 第一阶段：有匹配/缺口/简历建议，但【没有】学习路线
    assert result["roadmap"] == []
    assert 0 <= result["match_score"] <= 100
    assert result["skill_gap"]["must_have_gaps"]
    assert result["resume_suggestions"]
    # 进度里应能看到并行解析与缺口/建议步骤
    joined = " ".join(statuses)
    assert "解析" in joined and "技能缺口" in joined


def test_build_roadmap_respects_preferences():
    # 先得到缺口
    outcome = None
    for kind, payload in pipeline.analyze_match_streaming(SAMPLE_RESUME, SAMPLE_JDS, "前端实习"):
        if kind == "result":
            outcome = payload
    skill_gap = outcome["result"]["skill_gap"]

    # weekly_hours 应直接决定每周估时
    plan = pipeline.build_roadmap(skill_gap, 4, "前端实习", {"weekly_hours": 20})
    assert len(plan) == 4
    assert all(w["estimated_hours"] == 20 for w in plan if w["focus_skills"])

    # focus_skills 应把指定技能提前（出现在第 1 周）
    gap_names = [g["name"] for g in skill_gap["must_have_gaps"]]
    if len(gap_names) >= 2:
        target = gap_names[-1]  # 取一个本不在最前的
        plan2 = pipeline.build_roadmap(skill_gap, 4, "前端实习", {"focus_skills": [target]})
        assert target in plan2[0]["focus_skills"]


def test_full_run_still_has_roadmap():
    # 完整分析（脚本/兼容路径）仍应包含学习路线
    out = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, "前端实习", 3)
    assert len(out["result"]["roadmap"]) == 3


def test_conversation_crud(client):
    turns = [
        {"role": "user", "text": "帮我分析前端实习"},
        {"role": "assistant", "blocks": [{"kind": "text", "text": "好的"}]},
    ]
    # 新建
    r = client.post("/api/conversations", json={"title": "前端实习咨询", "turns": turns})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert cid > 0

    # 列表
    lst = client.get("/api/conversations").json()
    mine = next(c for c in lst if c["id"] == cid)
    assert mine["turn_count"] == 2
    assert mine["title"] == "前端实习咨询"

    # 详情（turns 原样返回）
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["turns"] == turns

    # 更新（同 id，追加一条）
    turns2 = turns + [{"role": "user", "text": "每周 10 小时"}]
    r2 = client.post("/api/conversations", json={"id": cid, "title": "前端实习咨询", "turns": turns2})
    assert r2.status_code == 200
    assert r2.json()["id"] == cid
    assert client.get(f"/api/conversations/{cid}").json()["turns"] == turns2


def test_conversation_404(client):
    assert client.get("/api/conversations/999999").status_code == 404


def test_conversation_persists_context(client):
    """会话应保存并返回 context（简历/JD 等），用于续聊与作为相关职位参考。"""
    ctx = {
        "resume_text": "我的简历",
        "jd_texts": ["JD-A 前端", "JD-B 全栈"],
        "target_role": "前端实习",
        "weeks": 6,
        "analysis_run_id": 3,
    }
    r = client.post(
        "/api/conversations",
        json={"title": "带上下文", "turns": [{"role": "user", "text": "hi"}], "context": ctx},
    )
    assert r.status_code == 200
    cid = r.json()["id"]

    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["context"] == ctx
    assert detail["context"]["jd_texts"] == ["JD-A 前端", "JD-B 全栈"]

    # 更新 context（追加一条 JD）后仍正确返回
    ctx2 = {**ctx, "jd_texts": ctx["jd_texts"] + ["JD-C 数据"]}
    client.post("/api/conversations", json={"id": cid, "title": "带上下文", "turns": [], "context": ctx2})
    assert client.get(f"/api/conversations/{cid}").json()["context"]["jd_texts"][-1] == "JD-C 数据"


def test_guard_blocks_generate_plan_in_same_turn(client, monkeypatch):
    """硬性约束：analyze_match 之后的同一轮，generate_plan 必须被拦截（强制等用户回答）。"""
    from app.database import SessionLocal
    from app.services import agent, llm

    # 强制走 LLM Agent 路径（实际 LLM 仍禁用，analyze_match 内部走规则解析）
    monkeypatch.setattr(llm, "streaming_supported", lambda: True)

    calls = {"n": 0}

    def fake_agent_stream(messages, tools=None, effort="medium"):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一步：调用 analyze_match
            yield {
                "type": "final",
                "content": None,
                "tool_calls": [{"id": "a1", "name": "analyze_match", "arguments": "{}"}],
                "finish": "tool_calls",
            }
        else:
            # 第二步：说几句并【企图】立刻生成计划——应被拦截
            yield {"type": "delta", "text": "匹配好了，先问你几个问题。"}
            yield {
                "type": "final",
                "content": "匹配好了，先问你几个问题。",
                "tool_calls": [{"id": "g1", "name": "generate_plan", "arguments": "{}"}],
                "finish": "tool_calls",
            }

    monkeypatch.setattr(llm, "agent_stream", fake_agent_stream)

    ctx = {"resume_text": SAMPLE_RESUME, "jd_texts": SAMPLE_JDS[:1], "target_role": "前端实习", "weeks": 4}
    db = SessionLocal()
    try:
        events = list(agent.run_turn([{"role": "user", "content": "分析"}], ctx, db, "off"))
    finally:
        db.close()

    reports = [d for ev, d in events if ev == "report"]
    # 只应有 1 个报告（来自 analyze_match），且 roadmap 为空；generate_plan 被拦截 → 无第二个报告
    assert len(reports) == 1
    assert reports[0]["result"]["roadmap"] == []
    # 仍应向用户输出文字（提问）
    assert any(ev == "delta" for ev, _ in events)
