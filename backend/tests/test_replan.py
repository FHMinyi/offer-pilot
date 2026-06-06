"""里程碑二 · E1.2 动态再规划引擎测试。

覆盖：顺延（逾期未完成滚到今天起）、重组（按容量摊到剩余日）、结算降权、
done 不被重排、同日幂等、HTTP 端点、打卡自动触发结算重排。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AnalysisRun, JourneyState, Resume, Task, _utcnow
from app.services import pipeline
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from app.services.replan import replan_journey
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _seed(db, weeks: int = 4, start_offset_days: int = 10) -> tuple[AnalysisRun, JourneyState]:
    """播一份旅程，start_date 设在过去，使前几周任务天然逾期。"""
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
    journey = ensure_journey(db, run, "local")
    journey.start_date = date.today() - timedelta(days=start_offset_days)
    db.commit()
    materialize_tasks(db, run, "local", journey)
    return run, journey


def test_replan_carries_overdue_forward_and_deprioritizes(client):
    db = SessionLocal()
    try:
        today = date.today()
        run, journey = _seed(db)
        before = db.scalars(
            select(Task).where(Task.analysis_run_id == run.id, Task.status != "skipped")
        ).all()
        overdue_before = [t for t in before if t.planned_date and t.planned_date < today]
        assert overdue_before, "种子应包含逾期任务"

        tasks = replan_journey(db, journey, today=today, settle=True)
        remaining = [t for t in tasks if t.status in ("todo", "doing") and t.planned_date]
        # 顺延：未完成任务全部 >= 今天
        assert remaining and all(t.planned_date >= today for t in remaining)
        # 降权：原逾期任务 weight 1→0
        overdue_ids = {t.id for t in overdue_before}
        for t in tasks:
            if t.id in overdue_ids:
                assert t.weight == 0
        # 信号 + 时间戳
        assert journey.last_replanned_at is not None
        assert journey.signals.get("carried_over") == len(overdue_before)
    finally:
        db.close()


def test_replan_redistributes_within_capacity(client):
    db = SessionLocal()
    try:
        today = date.today()
        _, journey = _seed(db)
        tasks = replan_journey(db, journey, today=today, settle=False)
        remaining = [t for t in tasks if t.status in ("todo", "doing") and t.planned_date]
        per_day = Counter(t.planned_date for t in remaining)
        assert len(per_day) >= 2  # 摊到多天
        assert all(d >= today for d in per_day)  # 无逾期残留
    finally:
        db.close()


def test_replan_keeps_done_tasks(client):
    db = SessionLocal()
    try:
        today = date.today()
        run, journey = _seed(db)
        rows = db.scalars(
            select(Task).where(Task.analysis_run_id == run.id).order_by(Task.id)
        ).all()
        done_task = rows[0]
        done_task.status = "done"
        done_task.done_at = _utcnow()
        db.commit()
        done_id, done_pd, done_w = done_task.id, done_task.planned_date, done_task.weight

        replan_journey(db, journey, today=today, settle=True)
        again = db.get(Task, done_id)
        assert again.status == "done"
        assert again.planned_date == done_pd  # done 不被重排
        assert again.weight == done_w  # done 不被降权
    finally:
        db.close()


def test_replan_idempotent_same_day(client):
    db = SessionLocal()
    try:
        today = date.today()
        run, journey = _seed(db)
        replan_journey(db, journey, today=today, settle=True)
        w1 = {t.id: t.weight for t in db.scalars(select(Task).where(Task.analysis_run_id == run.id)).all()}
        replan_journey(db, journey, today=today, settle=True)
        w2 = {t.id: t.weight for t in db.scalars(select(Task).where(Task.analysis_run_id == run.id)).all()}
        assert w1 == w2  # 同日二次结算无逾期 → 不再降权
    finally:
        db.close()


def test_replan_endpoint(client):
    db = SessionLocal()
    try:
        run, journey = _seed(db)
        jid = journey.id
    finally:
        db.close()

    r = client.post(f"/api/journey/{jid}/replan", json={"settle": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["journey"]["id"] == jid
    today_iso = date.today().isoformat()
    rem = [t for t in body["tasks"] if t["status"] in ("todo", "doing") and t["planned_date"]]
    assert rem and all(t["planned_date"] >= today_iso for t in rem)


def test_checkin_triggers_settlement_replan(client):
    db = SessionLocal()
    try:
        run, journey = _seed(db)
        jid, run_id = journey.id, run.id
        had_overdue = any(
            t.planned_date and t.planned_date < date.today()
            for t in db.scalars(
                select(Task).where(Task.analysis_run_id == run_id, Task.status == "todo")
            ).all()
        )
        assert had_overdue
    finally:
        db.close()

    # 打卡（无 header → 'local'，与旅程同属）触发结算重排
    r = client.post("/api/checkins", json={"date": date.today().isoformat(), "note": "settle"})
    assert r.status_code == 200

    db = SessionLocal()
    try:
        rem = db.scalars(
            select(Task).where(
                Task.analysis_run_id == run_id, Task.status.in_(("todo", "doing"))
            )
        ).all()
        assert rem and all(t.planned_date is None or t.planned_date >= date.today() for t in rem)
        assert db.get(JourneyState, jid).last_replanned_at is not None
    finally:
        db.close()
