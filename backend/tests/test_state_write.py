"""里程碑一 · C4 写入闭环 + materialize 接主链 + SSE user_id 穿透 测试。

覆盖：REST 分析→物化 Task/Journey、PATCH 任务完成度回灌、打卡 upsert、
SSE user_id 穿透使 generate_plan 物化的 Task 归属正确（防里程碑三脏行）、
PATCH 旅程、引用模式复用 Resume.structured。
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select

from app.database import SessionLocal
from app.models import JobPosting, JourneyState, Resume, Task
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _parse_sse(body: str) -> list[tuple[str, dict]]:
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


def _run_analysis(client, weeks: int = 3) -> int:
    r = client.post(
        "/api/analysis/run",
        json={
            "resume_text": SAMPLE_RESUME,
            "jd_texts": SAMPLE_JDS,
            "target_role": "前端实习",
            "weeks": weeks,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_analysis_run_materializes_tasks_and_journey(client):
    run_id = _run_analysis(client, weeks=3)
    tasks = client.get(f"/api/tasks?analysis_run_id={run_id}").json()
    assert len(tasks) > 0
    assert all(t["analysis_run_id"] == run_id for t in tasks)

    j = client.get("/api/journey")
    assert j.status_code == 200
    body = j.json()
    assert body["analysis_run_id"] == run_id
    assert body["planned_weeks"] == 3
    assert body["status"] == "active"


def test_patch_task_done_updates_progress(client):
    run_id = _run_analysis(client, weeks=3)
    tasks = client.get(f"/api/tasks?analysis_run_id={run_id}").json()
    before = client.get("/api/progress").json()

    t = tasks[0]
    pr = client.patch(f"/api/tasks/{t['id']}", json={"status": "done"})
    assert pr.status_code == 200
    body = pr.json()
    assert body["status"] == "done" and body["done"] is True and body["done_at"] is not None

    after = client.get("/api/progress").json()
    assert after["done_tasks"] == before["done_tasks"] + 1
    assert after["completion_rate"] > before["completion_rate"]

    # 取消完成 → 清空 done_at
    pr2 = client.patch(f"/api/tasks/{t['id']}", json={"status": "todo"})
    assert pr2.json()["done_at"] is None and pr2.json()["done"] is False


def test_patch_task_404(client):
    assert client.patch("/api/tasks/999999", json={"status": "done"}).status_code == 404


def test_checkin_upsert_single_row_per_day(client):
    today = date.today().isoformat()
    r1 = client.post("/api/checkins", json={"date": today, "note": "day1", "minutes": 30})
    assert r1.status_code == 200
    r2 = client.post("/api/checkins", json={"date": today, "note": "day1-edited", "minutes": 60})
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]  # 同日 upsert 同一行
    assert r2.json()["note"] == "day1-edited" and r2.json()["minutes"] == 60

    lst = client.get(f"/api/checkins?start={today}&end={today}").json()
    assert len(lst) == 1


def test_patch_journey(client):
    _run_analysis(client, weeks=4)
    j = client.get("/api/journey").json()
    pr = client.patch(f"/api/journey/{j['id']}", json={"stage": "applying", "current_week": 2})
    assert pr.status_code == 200
    assert pr.json()["stage"] == "applying" and pr.json()["current_week"] == 2
    assert client.patch("/api/journey/999999", json={"stage": "closing"}).status_code == 404


def test_chat_scripted_materializes_tasks_with_user_id(client):
    """脚本化降级路径（LLM none）经 SSE user_id 穿透，Task 归属 X-Device-Id。"""
    headers = {"X-Device-Id": "dev-zhang"}
    payload = {
        "messages": [{"role": "user", "content": "分析"}],
        "context": {
            "resume_text": SAMPLE_RESUME,
            "jd_texts": SAMPLE_JDS,
            "target_role": "前端实习",
            "weeks": 3,
        },
    }
    r = client.post("/api/chat/stream", json=payload, headers=headers)
    assert r.status_code == 200
    events = _parse_sse(r.text)
    report = next(d for e, d in events if e == "report")
    run_id = report["analysis_run_id"]

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Task).where(Task.analysis_run_id == run_id, Task.status != "skipped")
        ).all()
        assert rows
        assert all(t.user_id == "dev-zhang" for t in rows)  # 防脏行：归属正确
        j = db.scalars(
            select(JourneyState)
            .where(JourneyState.user_id == "dev-zhang")
            .order_by(JourneyState.id.desc())
        ).first()
        assert j is not None and j.analysis_run_id == run_id
    finally:
        db.close()


def test_llm_generate_plan_materializes_with_user_id(monkeypatch):
    """LLM 路径两轮：analyze_match → generate_plan，断言 Task 物化且 user_id 穿透正确。"""
    from app.services import agent, llm

    monkeypatch.setattr(llm, "streaming_supported", lambda: True)
    state = {"phase": 0, "run_id": None}

    def fake_stream(messages, tools=None, effort="medium"):
        state["phase"] += 1
        p = state["phase"]
        if p == 1:  # 第一轮：匹配分析
            yield {
                "type": "final",
                "content": None,
                "tool_calls": [{"id": "a1", "name": "analyze_match", "arguments": "{}"}],
                "finish": "tool_calls",
            }
        elif p == 2:  # 第一轮收尾：反问、无工具
            yield {"type": "delta", "text": "匹配完成，每周几小时？"}
            yield {"type": "final", "content": "...", "tool_calls": [], "finish": "stop"}
        elif p == 3:  # 第二轮：生成计划
            args = json.dumps({"analysis_run_id": state["run_id"], "weeks": 3})
            yield {
                "type": "final",
                "content": None,
                "tool_calls": [{"id": "g1", "name": "generate_plan", "arguments": args}],
                "finish": "tool_calls",
            }
        else:  # 第二轮收尾
            yield {"type": "final", "content": "计划已生成", "tool_calls": [], "finish": "stop"}

    monkeypatch.setattr(llm, "agent_stream", fake_stream)
    ctx = {
        "resume_text": SAMPLE_RESUME,
        "jd_texts": SAMPLE_JDS[:2],
        "target_role": "前端实习",
        "weeks": 4,
    }

    db = SessionLocal()
    try:
        ev1 = list(agent.run_turn([{"role": "user", "content": "分析"}], ctx, db, "off", "", user_id="dev-y"))
    finally:
        db.close()
    rep1 = next(d for e, d in ev1 if e == "report")
    state["run_id"] = rep1["analysis_run_id"]
    assert rep1["result"]["roadmap"] == []  # 匹配阶段无路线

    db = SessionLocal()
    try:
        ev2 = list(
            agent.run_turn([{"role": "user", "content": "每周10小时"}], ctx, db, "off", "", user_id="dev-y")
        )
    finally:
        db.close()
    rep2 = [d for e, d in ev2 if e == "report"]
    assert rep2 and rep2[-1]["result"]["roadmap"]  # 已生成路线

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Task).where(Task.analysis_run_id == state["run_id"], Task.status != "skipped")
        ).all()
        assert rows
        assert all(t.user_id == "dev-y" for t in rows)  # SSE user_id 穿透到物化
        j = db.scalars(
            select(JourneyState).where(JourneyState.user_id == "dev-y").order_by(JourneyState.id.desc())
        ).first()
        assert j is not None and j.analysis_run_id == state["run_id"]
    finally:
        db.close()


def test_reference_mode_reuses_resume_structured(client, monkeypatch):
    """引用模式（resume_id）应复用 Resume.structured，不重解析简历。"""
    from app.services import resume_parser
    from app.services import pipeline as pl

    db = SessionLocal()
    try:
        structured = resume_parser.parse_resume(SAMPLE_RESUME)
        resume = Resume(raw_text=SAMPLE_RESUME, structured=structured, source_type="paste")
        db.add(resume)
        db.flush()
        job_ids = []
        for jd in SAMPLE_JDS:
            jp = JobPosting(title="", company="", raw_text=jd, structured={})
            db.add(jp)
            db.flush()
            job_ids.append(jp.id)
        db.commit()
        resume_id = resume.id
    finally:
        db.close()

    def boom(*a, **k):
        raise AssertionError("引用模式不应重解析简历")

    monkeypatch.setattr(pl.resume_parser, "parse_resume", boom)

    r = client.post(
        "/api/analysis/run",
        json={"resume_id": resume_id, "job_ids": job_ids, "target_role": "前端实习", "weeks": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["resume_id"] == resume_id
