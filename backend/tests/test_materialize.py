"""里程碑一 · C2 物化契约 + Resume.structured 复用 测试。

纯服务层验证（不接路由）：roadmap→Task 数量/唯一键/幂等/软删/进度保留、
journey 幂等与归属、引用模式复用结构化简历跳过重解析。
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AnalysisRun, Resume, Task, _utcnow
from app.services import pipeline, resume_parser
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _expected_count(roadmap: list[dict]) -> int:
    return sum(
        len(w.get("tasks") or [])
        + len(w.get("deliverables") or [])
        + len(w.get("interview_focus") or [])
        for w in roadmap
    )


def _make_run(db, weeks: int = 4) -> AnalysisRun:
    outcome = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, target_role="前端实习", weeks=weeks)
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
    return run


def test_materialize_produces_expected_tasks(client):
    db = SessionLocal()
    try:
        run = _make_run(db, weeks=4)
        roadmap = run.result["roadmap"]
        tasks = materialize_tasks(db, run, "local")

        assert len(tasks) == _expected_count(roadmap) > 0
        keys = {(t.week, t.order_index) for t in tasks}
        assert len(keys) == len(tasks)  # (week, order_index) 唯一
        assert all(
            t.status == "todo" and t.user_id == "local" and t.analysis_run_id == run.id
            for t in tasks
        )
        # 每周 order_index 从 0 连续
        by_week: dict[int, list[int]] = {}
        for t in tasks:
            by_week.setdefault(t.week, []).append(t.order_index)
        for week, idxs in by_week.items():
            assert sorted(idxs) == list(range(len(idxs)))
    finally:
        db.close()


def test_materialize_idempotent_and_preserves_progress(client):
    db = SessionLocal()
    try:
        run = _make_run(db, weeks=4)
        tasks = materialize_tasks(db, run, "local")
        n = len(tasks)

        # 标一个 done，再重跑物化（同 run 同 result）
        t0 = tasks[0]
        t0.status = "done"
        t0.done_at = _utcnow()
        db.commit()
        t0_id = t0.id

        tasks2 = materialize_tasks(db, run, "local")
        assert len(tasks2) == n  # 活跃数不变
        all_rows = db.scalars(select(Task).where(Task.analysis_run_id == run.id)).all()
        assert len(all_rows) == n  # 物理行不翻倍（幂等）

        again = db.get(Task, t0_id)
        assert again.status == "done" and again.done_at is not None  # 进度保留
    finally:
        db.close()


def test_materialize_week_shrink_soft_deletes(client):
    db = SessionLocal()
    try:
        run = _make_run(db, weeks=4)
        materialize_tasks(db, run, "local")
        full = len(db.scalars(select(Task).where(Task.analysis_run_id == run.id)).all())

        # roadmap 缩到只剩第 1 周后重物化
        run.result = {**run.result, "roadmap": run.result["roadmap"][:1]}
        db.commit()
        materialize_tasks(db, run, "local")

        active = db.scalars(
            select(Task).where(Task.analysis_run_id == run.id, Task.status != "skipped")
        ).all()
        skipped = db.scalars(
            select(Task).where(Task.analysis_run_id == run.id, Task.status == "skipped")
        ).all()
        all_rows = db.scalars(select(Task).where(Task.analysis_run_id == run.id)).all()

        assert len(active) < full
        assert len(skipped) > 0
        assert len(all_rows) == full  # 软删不物删，物理行数不减
    finally:
        db.close()


def test_ensure_journey_idempotent_and_per_user(client):
    db = SessionLocal()
    try:
        run = _make_run(db, weeks=6)
        j1 = ensure_journey(db, run, "local")
        assert j1.status == "active" and j1.user_id == "local"
        assert j1.analysis_run_id == run.id and j1.planned_weeks == 6
        assert j1.target_role == "前端实习"

        run2 = _make_run(db, weeks=4)
        j2 = ensure_journey(db, run2, "local")
        assert j2.id == j1.id  # 同一活跃旅程被复用
        assert j2.analysis_run_id == run2.id and j2.planned_weeks == 4

        j_other = ensure_journey(db, run2, "dev-x")
        assert j_other.id != j1.id and j_other.user_id == "dev-x"  # 不同 user 独立
    finally:
        db.close()


def test_materialize_links_journey_and_planned_date(client):
    db = SessionLocal()
    try:
        run = _make_run(db, weeks=4)
        journey = ensure_journey(db, run, "local")
        tasks = materialize_tasks(db, run, "local", journey)
        assert tasks and all(t.journey_id == journey.id for t in tasks)
        for t in tasks:
            if journey.start_date and t.planned_date:
                assert t.planned_date == journey.start_date + timedelta(days=(t.week - 1) * 7)
    finally:
        db.close()


def test_resume_structured_reuse_skips_parser(client):
    real_structured = resume_parser.parse_resume(SAMPLE_RESUME)  # 规则模式真解析一次
    with mock.patch.object(pipeline.resume_parser, "parse_resume") as m:
        outcome = pipeline.run_analysis(
            SAMPLE_RESUME, SAMPLE_JDS, "前端实习", 4, resume_structured=real_structured
        )
        m.assert_not_called()  # 复用结构 → 不重解析简历
    assert outcome["resume"] is real_structured
    assert outcome["result"]["roadmap"]  # 仍产出完整结果


def test_without_structured_parser_is_called(client):
    with mock.patch.object(
        pipeline.resume_parser, "parse_resume", wraps=resume_parser.parse_resume
    ) as m:
        pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, "前端实习", 4)
        assert m.call_count == 1  # 不传 structured → 正常解析
