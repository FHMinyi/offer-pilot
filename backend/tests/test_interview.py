"""轨道 F1 · 面经复盘 → 盲区提取 → 权重回灌 测试。

conftest 固定 LLM_PROVIDER=none，故盲区提取走规则路径（match_skills 命中技能本体）。
覆盖：规则抽取、空文本、reweight 命中提权+拉到今天+未命中不动、weight 封顶、
API 端到端（回包/持久化/matched 标记）、列表、无活跃旅程也能存档。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete

from app.database import SessionLocal
from app.models import AnalysisRun, CheckIn, InterviewLog, JourneyState, Resume, Task
from app.services import pipeline
from app.services.interview import extract_blind_spots, reweight_from_blind_spots
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _wipe():
    db = SessionLocal()
    try:
        for model in (InterviewLog, CheckIn, Task, JourneyState):
            db.execute(delete(model))
        db.commit()
    finally:
        db.close()


def _seed_journey(weeks: int = 4) -> dict:
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
        journey = ensure_journey(db, run, "local")
        materialize_tasks(db, run, "local", journey)
        return {"run_id": run.id, "journey_id": journey.id}
    finally:
        db.close()


def _spot(key: str, name: str, severity: str = "high") -> dict:
    return {"skill_key": key, "skill_name": name, "severity": severity, "evidence": [], "matched": False}


# ---------------------------------------------------------------- 盲区抽取

def test_extract_blind_spots_rule():
    spots = extract_blind_spots("面试被问到 TypeScript 的泛型和 Docker 部署，都答不上来。")
    keys = {s["skill_key"] for s in spots}
    assert "typescript" in keys
    assert "docker" in keys
    # 规则路径无 run 交叉 → 严重度恒为 mid（守住契约，而非宽松地「属于三档之一」）
    assert all(s["severity"] == "mid" for s in spots)
    assert all(s["matched"] is False for s in spots)  # 抽取阶段尚未匹配任务


def test_extract_blind_spots_empty():
    assert extract_blind_spots("   ") == []


# ---------------------------------------------------------------- 权重回灌

def test_reweight_boosts_and_pulls_to_today():
    info = _seed_journey()
    db = SessionLocal()
    try:
        journey = db.get(JourneyState, info["journey_id"])
        hit = Task(
            user_id="local", journey_id=journey.id, analysis_run_id=info["run_id"],
            week=1, order_index=900, skill_key="TypeScript", title="深入 TypeScript 类型系统",
            kind="learn", weight=1, status="todo", planned_date=date(2020, 1, 1),
        )
        miss = Task(
            user_id="local", journey_id=journey.id, analysis_run_id=info["run_id"],
            week=1, order_index=901, skill_key="SQL", title="练习 SQL 查询优化",
            kind="learn", weight=1, status="todo", planned_date=date(2020, 1, 1),
        )
        db.add_all([hit, miss])
        db.commit()
        hit_id, miss_id = hit.id, miss.id
        res = reweight_from_blind_spots(
            db, journey, [_spot("typescript", "TypeScript", "high")], today=date(2026, 6, 6)
        )
        assert hit_id in {t.id for t in res["boosted"]}
        assert miss_id not in {t.id for t in res["boosted"]}
        assert "typescript" in res["matched_keys"]
        db.commit()  # reweight 只 flush，提交由调用方负责（与路由同口径）
    finally:
        db.close()
    # 持久化校验
    db = SessionLocal()
    try:
        h, m = db.get(Task, hit_id), db.get(Task, miss_id)
        assert h.weight == 1 + 4 and h.planned_date == date(2026, 6, 6)  # high=+4
        assert m.weight == 1 and m.planned_date == date(2020, 1, 1)  # 未命中不动
    finally:
        db.close()


def test_reweight_caps_weight_at_10():
    info = _seed_journey()
    db = SessionLocal()
    try:
        journey = db.get(JourneyState, info["journey_id"])
        t = Task(
            user_id="local", journey_id=journey.id, analysis_run_id=info["run_id"],
            week=1, order_index=950, skill_key="TypeScript", title="TypeScript 进阶",
            kind="learn", weight=9, status="todo",
        )
        db.add(t)
        db.commit()
        tid = t.id
        reweight_from_blind_spots(
            db, journey, [_spot("typescript", "TypeScript", "high")], today=date(2026, 6, 6)
        )
        db.commit()  # reweight 只 flush，提交由调用方负责
    finally:
        db.close()
    db = SessionLocal()
    try:
        assert db.get(Task, tid).weight == 10  # 9+4 封顶 10
    finally:
        db.close()


def test_reweight_skips_done_tasks():
    info = _seed_journey()
    db = SessionLocal()
    try:
        journey = db.get(JourneyState, info["journey_id"])
        t = Task(
            user_id="local", journey_id=journey.id, analysis_run_id=info["run_id"],
            week=1, order_index=970, skill_key="TypeScript", title="TypeScript 基础",
            kind="learn", weight=1, status="done",
        )
        db.add(t)
        db.commit()
        tid = t.id
        res = reweight_from_blind_spots(
            db, journey, [_spot("typescript", "TypeScript", "high")], today=date(2026, 6, 6)
        )
        assert tid not in {x.id for x in res["boosted"]}  # 已完成不回灌
        db.commit()
    finally:
        db.close()
    db = SessionLocal()
    try:
        assert db.get(Task, tid).weight == 1
    finally:
        db.close()


# ---------------------------------------------------------------- API

def test_create_interview_api(client):
    info = _seed_journey()
    db = SessionLocal()
    try:
        journey = db.get(JourneyState, info["journey_id"])
        db.add(
            Task(
                user_id="local", journey_id=journey.id, analysis_run_id=info["run_id"],
                week=1, order_index=960, skill_key="React", title="学习 React Hooks 原理",
                kind="learn", weight=1, status="todo", planned_date=date(2020, 1, 1),
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/interviews",
        json={
            "content": "被问 React Hooks 原理，没答好。",
            "company": "某公司",
            "role": "前端实习",
            "today": "2026-06-06",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "react" in {s["skill_key"] for s in body["interview"]["blind_spots"]}
    # react 命中受控任务 → boosted 非空，全部 planned_date 拉到今天、weight 提升
    assert body["boosted_tasks"], "命中盲区的任务应被回灌"
    assert any("React" in t["title"] for t in body["boosted_tasks"])
    assert all(t["planned_date"] == "2026-06-06" for t in body["boosted_tasks"])
    assert all(t["weight"] >= 2 for t in body["boosted_tasks"])
    # 命中盲区 matched=True 并已持久化
    react_spot = next(s for s in body["interview"]["blind_spots"] if s["skill_key"] == "react")
    assert react_spot["matched"] is True


def test_list_interviews(client):
    _wipe()
    assert client.get("/api/interviews").json() == []
    _seed_journey()
    client.post("/api/interviews", json={"content": "被问 Docker 不会用", "today": "2026-06-06"})
    lst = client.get("/api/interviews").json()
    assert len(lst) == 1
    assert "docker" in {s["skill_key"] for s in lst[0]["blind_spots"]}


def test_interview_without_journey_saves_no_reweight(client):
    _wipe()  # 无旅程
    r = client.post("/api/interviews", json={"content": "被问 Docker 不熟", "today": "2026-06-06"})
    assert r.status_code == 200
    body = r.json()
    assert body["boosted_tasks"] == []  # 无活跃旅程 → 不回灌
    # docker 是盲区但无任务可命中 → 进 unmatched（建议加练）
    assert "docker" in {s["skill_key"] for s in body["unmatched_skills"]}
