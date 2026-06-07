"""费曼/出题判定学习掌握度（学习闭环引擎第二个实例）测试。

conftest 固定 LLM_PROVIDER=none，故判定走「降级」路径：不返回假判定、available=False、
不自动 mastered（呼应「AI 缺席不卡死用户」）。覆盖：服务层降级、gaps 归一契约（与 F1 同构）、
双层状态机（自评升级 / mastered 隐含 done / 取消勾选级联降级）、仅 learn 约束、API 端到端、
真掌握率聚合（done 口径向后兼容）、记录回看。
"""

from __future__ import annotations

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import (
    AnalysisRun,
    CheckIn,
    InterviewLog,
    JourneyState,
    MasteryCheck,
    Resume,
    Task,
)
from app.services import pipeline
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from app.services.mastery import gaps_to_blind_spots, generate_quiz, judge_feynman
from tests.sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _wipe():
    db = SessionLocal()
    try:
        for model in (MasteryCheck, InterviewLog, CheckIn, Task, JourneyState):
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
            resume_id=resume.id, job_ids=[], target_role="前端实习", weeks=weeks,
            match_score=outcome["result"]["match_score"], result=outcome["result"],
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


def _a_learn_task(run_id: int) -> int:
    db = SessionLocal()
    try:
        t = db.scalars(
            select(Task).where(Task.analysis_run_id == run_id, Task.kind == "learn")
        ).first()
        assert t is not None, "样例 roadmap 应物化出 learn 任务"
        return t.id
    finally:
        db.close()


# --------------------------------------------------- 服务层降级 / gaps 归一契约

def test_judge_feynman_degrades_without_llm():
    task = Task(kind="learn", title="React Hooks 原理", skill_key="React", weight=1, status="done")
    res = judge_feynman("Hooks 让函数组件能用状态和副作用……", task)
    assert res["available"] is False
    assert res["verdict"] == ""
    assert res["passed"] is False
    assert res["gaps"] == []
    assert "手动标记" in res["feedback"]  # 降级文案引导走「我已掌握」


def test_generate_quiz_degrades_without_llm():
    task = Task(kind="learn", title="HTTP 缓存", skill_key="HTTP", weight=1, status="todo")
    res = generate_quiz(task)
    assert res["available"] is False
    assert res["questions"] == []


def test_gaps_to_blind_spots_normalizes():
    spots = gaps_to_blind_spots([{"skill": "TypeScript", "severity": "high", "evidence": "泛型不熟"}])
    assert spots and spots[0]["skill_key"] == "typescript"
    s = spots[0]
    assert s["severity"] == "high"
    assert s["matched"] is False
    assert "泛型不熟" in s["evidence"]
    # 与 InterviewLog.blind_spots 完全同构 → 可直接喂 reweight_from_blind_spots
    assert set(s.keys()) == {"skill_key", "skill_name", "severity", "evidence", "matched"}


# --------------------------------------------------- 双层状态机 / 仅 learn / API

def test_master_task_sets_mastered_and_done(client):
    info = _seed_journey()
    tid = _a_learn_task(info["run_id"])
    r = client.post(f"/api/mastery/tasks/{tid}/master", json={"today": "2026-06-06"})
    assert r.status_code == 200
    body = r.json()
    assert body["mastery"] == "mastered"
    assert body["mastered"] is True
    assert body["status"] == "done"  # mastered 隐含 done
    assert body["done_at"] is not None
    # manual 留痕，保证真掌握率有据可查
    lst = client.get("/api/mastery").json()
    assert len(lst) == 1
    assert lst[0]["engine"] == "manual"
    assert lst[0]["passed"] is True


def test_master_rejects_non_learn(client):
    info = _seed_journey()
    db = SessionLocal()
    try:
        t = Task(
            user_id="local", journey_id=info["journey_id"], analysis_run_id=info["run_id"],
            week=1, order_index=800, skill_key="", title="完成 TodoMVC 作品",
            kind="deliverable", weight=1, status="done",
        )
        db.add(t)
        db.commit()
        tid = t.id
    finally:
        db.close()
    assert client.post(f"/api/mastery/tasks/{tid}/master", json={}).status_code == 422


def test_feynman_api_degraded_does_not_auto_master(client):
    info = _seed_journey()
    tid = _a_learn_task(info["run_id"])
    r = client.post(
        "/api/mastery/feynman",
        json={"task_id": tid, "content": "我觉得 Hooks 就是函数里用状态。", "today": "2026-06-06"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["check"]["passed"] is False
    assert body["task"]["mastery"] == "unknown"  # 降级不自动 mastered，不卡死用户
    # 即使降级也存档，可回看
    assert client.get("/api/mastery").json()[0]["task_id"] == tid


def test_quiz_generate_and_judge_degraded(client):
    info = _seed_journey()
    tid = _a_learn_task(info["run_id"])
    g = client.post("/api/mastery/quiz/generate", json={"task_id": tid})
    assert g.status_code == 200
    assert g.json()["available"] is False
    assert g.json()["questions"] == []
    j = client.post(
        "/api/mastery/quiz/judge",
        json={
            "task_id": tid,
            "questions": [{"q": "什么是闭包？", "hint": ""}],
            "answers": ["不知道"],
            "today": "2026-06-06",
        },
    )
    assert j.status_code == 200
    assert j.json()["available"] is False
    assert j.json()["task"]["mastery"] == "unknown"


def test_uncheck_downgrades_mastery(client):
    info = _seed_journey()
    tid = _a_learn_task(info["run_id"])
    client.post(f"/api/mastery/tasks/{tid}/master", json={})
    # 取消勾选（done→todo）应级联降级 mastery，避免「未完成却 mastered」脏态
    r = client.patch(f"/api/tasks/{tid}", json={"status": "todo"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "todo"
    assert body["mastery"] == "unknown"
    assert body["mastered"] is False
    assert body["mastered_at"] is None


def test_progress_mastery_rate(client):
    info = _seed_journey()
    tid = _a_learn_task(info["run_id"])
    before = client.get("/api/progress", params={"today": "2026-06-06"}).json()
    client.post(f"/api/mastery/tasks/{tid}/master", json={"today": "2026-06-06"})
    after = client.get("/api/progress", params={"today": "2026-06-06"}).json()
    assert after["mastered_tasks"] == before["mastered_tasks"] + 1
    assert after["total_learn_tasks"] >= 1
    assert after["mastery_rate"] > 0
    # done 口径向后兼容：master 隐含 done，done_tasks 至少 +1（既有语义不变）
    assert after["done_tasks"] >= before["done_tasks"] + 1


def test_list_mastery_empty(client):
    _wipe()
    assert client.get("/api/mastery").json() == []
