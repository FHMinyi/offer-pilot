"""里程碑一 · C3 只读聚合 API 测试。

覆盖空态零值/404、放行（foo 与无头读同份数据）、过滤、聚合与 streak。
注意：测试库 session 级共享，空态用例先清三张状态表以排除前序用例残留。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import AnalysisRun, CheckIn, JourneyState, Resume, Task, _utcnow
from app.services import pipeline
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _wipe():
    db = SessionLocal()
    try:
        db.execute(delete(CheckIn))
        db.execute(delete(Task))
        db.execute(delete(JourneyState))
        db.commit()
    finally:
        db.close()


def _seed(user_id: str = "local", weeks: int = 4) -> dict:
    """清空三表后播一份真实数据（Resume+AnalysisRun+Journey+Tasks）。返回 id 信息。"""
    _wipe()
    db = SessionLocal()
    try:
        outcome = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, "前端实习", weeks)
        resume = Resume(raw_text=SAMPLE_RESUME, structured=outcome["resume"], source_type="paste")
        db.add(resume)
        db.flush()
        run = AnalysisRun(
            resume_id=resume.id,
            job_ids=[],
            target_role="前端实习",
            weeks=weeks,
            match_score=outcome["result"]["match_score"],
            result=outcome["result"],
            engine=outcome["engine"],
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        journey = ensure_journey(db, run, user_id)
        tasks = materialize_tasks(db, run, user_id, journey)
        return {
            "run_id": run.id,
            "journey_id": journey.id,
            "task_ids": [t.id for t in tasks],
            "task_count": len(tasks),
        }
    finally:
        db.close()


def test_tasks_empty_returns_list(client):
    _wipe()
    r = client.get("/api/tasks")
    assert r.status_code == 200 and r.json() == []


def test_journey_404_when_empty(client):
    _wipe()
    r = client.get("/api/journey")
    assert r.status_code == 404
    assert "尚无进行中的旅程" in r.json()["detail"]


def test_progress_empty_returns_zeros(client):
    _wipe()
    j = client.get("/api/progress").json()
    assert j["total_tasks"] == 0 and j["done_tasks"] == 0
    assert j["completion_rate"] == 0.0
    assert j["week_progress"] == []
    assert j["current_streak"] == 0 and j["longest_streak"] == 0
    assert j["checked_in_today"] is False
    assert j["last_checkin_date"] is None
    assert j["current_week"] == 1


def test_passthrough_foo_and_no_header_read_same(client):
    info = _seed("local", weeks=4)
    assert info["task_count"] > 0

    none = client.get("/api/tasks").json()
    foo = client.get("/api/tasks", headers={"X-Device-Id": "foo"}).json()
    assert len(none) == info["task_count"]
    assert none == foo  # 本期放行：改 header 读到同一份数据

    nj = client.get("/api/journey")
    fj = client.get("/api/journey", headers={"X-Device-Id": "foo"})
    assert nj.status_code == 200 and fj.status_code == 200
    assert nj.json() == fj.json()


def test_tasks_filter_by_run_and_week(client):
    info = _seed("local", weeks=4)
    all_t = client.get(f"/api/tasks?analysis_run_id={info['run_id']}").json()
    assert len(all_t) == info["task_count"]
    assert all(t["analysis_run_id"] == info["run_id"] for t in all_t)
    assert all("done" in t and t["done"] is False for t in all_t)  # 便利冗余字段

    wk1 = client.get(f"/api/tasks?analysis_run_id={info['run_id']}&week=1").json()
    assert wk1 and all(t["week"] == 1 for t in wk1)
    assert len(wk1) <= len(all_t)
    # (week, order_index) 升序
    keys = [(t["week"], t["order_index"]) for t in all_t]
    assert keys == sorted(keys)


def test_journey_shape(client):
    info = _seed("local", weeks=6)
    j = client.get("/api/journey").json()
    assert j["id"] == info["journey_id"]
    assert j["target_role"] == "前端实习"
    assert j["stage"] == "executing"
    assert j["status"] == "active"
    assert j["planned_weeks"] == 6
    assert j["analysis_run_id"] == info["run_id"]


def test_progress_aggregates_seeded(client):
    info = _seed("local", weeks=4)
    db = SessionLocal()
    try:
        tasks = db.scalars(
            select(Task).where(Task.analysis_run_id == info["run_id"])
        ).all()
        for t in tasks[:2]:
            t.status = "done"
            t.done_at = _utcnow()
        db.add(
            CheckIn(
                user_id="local",
                journey_id=info["journey_id"],
                date=date.today(),
                completed_task_ids=[tasks[0].id],
            )
        )
        db.commit()
    finally:
        db.close()

    p = client.get("/api/progress").json()
    assert p["total_tasks"] == info["task_count"]
    assert p["done_tasks"] == 2
    assert 0 < p["completion_rate"] <= 1
    assert p["checked_in_today"] is True
    assert p["current_streak"] >= 1
    assert p["last_checkin_date"] == date.today().isoformat()
    assert sum(w["total"] for w in p["week_progress"]) == info["task_count"]
    assert sum(w["done"] for w in p["week_progress"]) == 2


def test_progress_streak_two_consecutive_days(client):
    info = _seed("local", weeks=4)
    db = SessionLocal()
    try:
        today = date.today()
        for d in (today - timedelta(days=1), today):
            db.add(CheckIn(user_id="local", journey_id=info["journey_id"], date=d))
        db.commit()
    finally:
        db.close()
    p = client.get("/api/progress").json()
    assert p["current_streak"] == 2
    assert p["longest_streak"] >= 2
