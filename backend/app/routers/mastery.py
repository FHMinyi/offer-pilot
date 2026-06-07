"""掌握度判定路由（费曼/出题 · 学习闭环引擎的第二个实例）。

把「完成」从点勾(done)升级到「真掌握」(mastered ⭐)：用户复述/答题 → AI 判定 →
（passed 则升级 task）→ 缺口回灌（复用 F1 的 reweight_from_blind_spots）→ 存档可回看。

事务边界（比 F1 更稳一档）：
- 阶段A：判定本体(MasteryCheck) + 「passed 则升级 task」一起原子提交 —— 这是判定的核心
  结果，不应被回灌副作用连累。
- 阶段B：缺口回灌（命中盲区的其它未完成任务提 weight + 拉到今天）+ matched 回填，
  try/except 包裹，失败 rollback 只撤销 B，阶段A 已落库不受影响。

降级：服务层无 LLM 时返回 available=False 的温和结果（不假判定）；本路由如实透传，
前端据此引导走「我已掌握」。/master 端点不依赖 LLM，永远可用，是 AI 缺席的兜底。
仅 learn 类任务可判定（_require_learn 422）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import JourneyState, MasteryCheck, Task
from ..ownership import require_owned, scope_to_user
from ..schemas import (
    BlindSpotItem,
    FeynmanJudgeRequest,
    MasterTaskRequest,
    MasteryCheckOut,
    MasteryJudgeOut,
    QuizGenerateOut,
    QuizGenerateRequest,
    QuizJudgeRequest,
    QuizQuestion,
    TaskOut,
)
from ..services.interview import reweight_from_blind_spots
from ..services.mastery import generate_quiz, judge_feynman, judge_quiz

logger = logging.getLogger("offerpilot.mastery")

router = APIRouter(prefix="/api/mastery", tags=["mastery"])


def _latest_active_journey(db: Session, user_id: str) -> JourneyState | None:
    stmt = scope_to_user(
        select(JourneyState).where(JourneyState.status == "active"),
        JourneyState,
        user_id,
    ).order_by(JourneyState.id.desc())
    return db.scalars(stmt).first()


def _require_learn(task: Task) -> None:
    """掌握度判定仅作用于学习类任务（deliverable 看交付物 / interview 走模拟面试）。"""
    if task.kind != "learn":
        raise HTTPException(status_code=422, detail="仅学习类（learn）任务支持掌握度判定")


def _mark_mastered(task: Task) -> None:
    """升级为 mastered ⭐；mastered 隐含 done（确保 status/done_at 就位）。"""
    now = datetime.now(timezone.utc)
    task.mastery = "mastered"
    task.mastered_at = task.mastered_at or now
    if task.status != "done":
        task.status = "done"
    task.done_at = task.done_at or now


def _format_qa(questions: list[dict], answers: list[str]) -> str:
    """把出题模式的题目+答案拼成可回看的文本，存进 MasteryCheck.user_input。"""
    lines: list[str] = []
    for i, q in enumerate(questions):
        prompt = q.get("q", "") if isinstance(q, dict) else str(q)
        ans = answers[i] if i < len(answers) else ""
        lines.append(f"Q{i + 1}: {prompt}\nA{i + 1}: {ans}")
    return "\n\n".join(lines)


def _finalize(
    db: Session,
    user_id: str,
    task: Task,
    *,
    mode: str,
    user_input: str,
    questions: list[dict],
    result: dict,
    today: date | None,
) -> MasteryJudgeOut:
    """判定结果落库（费曼/出题在 verdict 之后共用此处）：存档 + 升级 + 回灌 + 回包。"""
    journey = _latest_active_journey(db, user_id)
    gaps = result.get("gaps") or []  # 服务层已归一为 blind_spots 同构结构

    # 阶段A：判定本体 +（passed 则升级 task）原子提交，核心结果不受回灌影响。
    check = MasteryCheck(
        user_id=user_id,
        journey_id=journey.id if journey is not None else None,
        analysis_run_id=journey.analysis_run_id if journey is not None else None,
        task_id=task.id,
        mode=mode,
        user_input=user_input,
        questions=list(questions),
        verdict=result.get("verdict") or "",
        passed=bool(result.get("passed")),
        feedback=result.get("feedback") or "",
        followup_questions=list(result.get("followup_questions") or []),
        gaps=list(gaps),
        engine=result.get("engine") or "rule",
    )
    db.add(check)
    if result.get("passed"):
        _mark_mastered(task)
    db.commit()
    db.refresh(check)
    db.refresh(task)

    # 阶段B：缺口回灌（命中盲区的其它未完成任务提权 + 拉到今天）。失败不连累阶段A。
    boosted: list = []
    matched_keys: set[str] = set()
    if journey is not None and gaps:
        try:
            res = reweight_from_blind_spots(db, journey, gaps, today=today)
            boosted = res["boosted"]
            matched_keys = res["matched_keys"]
            for s in gaps:
                s["matched"] = s["skill_key"] in matched_keys
            check.gaps = list(gaps)  # 重新赋值触发 JSON 字段变更检测
            db.commit()
            db.refresh(check)
        except Exception:  # noqa: BLE001 回灌失败不连累已存判定本体，但要留痕
            logger.exception("判定缺口回灌失败，已回滚（判定本体已保存）")
            db.rollback()
            boosted, matched_keys = [], set()

    unmatched = [s for s in (check.gaps or []) if not s.get("matched")]
    return MasteryJudgeOut(
        check=MasteryCheckOut.model_validate(check),
        task=TaskOut.model_validate(task),
        available=bool(result.get("available", True)),
        boosted_tasks=[TaskOut.model_validate(t) for t in boosted],
        unmatched_skills=[BlindSpotItem.model_validate(s) for s in unmatched],
    )


@router.post("/feynman", response_model=MasteryJudgeOut)
def judge_feynman_endpoint(
    payload: FeynmanJudgeRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> MasteryJudgeOut:
    """费曼模式：提交复述 → AI 判定 →（passed 则标 mastered）→ 缺口回灌。"""
    task = require_owned(db, Task, payload.task_id, user_id)
    _require_learn(task)
    result = judge_feynman(payload.content, task)
    return _finalize(
        db, user_id, task,
        mode="feynman", user_input=payload.content, questions=[],
        result=result, today=payload.today,
    )


@router.post("/quiz/generate", response_model=QuizGenerateOut)
def generate_quiz_endpoint(
    payload: QuizGenerateRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> QuizGenerateOut:
    """出题模式第一步：为某 learn 任务生成 2-3 道题（无状态，questions 由前端持有回传）。"""
    task = require_owned(db, Task, payload.task_id, user_id)
    _require_learn(task)
    res = generate_quiz(task)
    return QuizGenerateOut(
        task_id=task.id,
        questions=[QuizQuestion(**q) for q in res["questions"]],
        available=res["available"],
    )


@router.post("/quiz/judge", response_model=MasteryJudgeOut)
def judge_quiz_endpoint(
    payload: QuizJudgeRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> MasteryJudgeOut:
    """出题模式第二步：提交答案判分 → 与费曼判定在 verdict 之后完全合流。"""
    task = require_owned(db, Task, payload.task_id, user_id)
    _require_learn(task)
    questions = [q.model_dump() for q in payload.questions]
    result = judge_quiz(questions, payload.answers, task)
    return _finalize(
        db, user_id, task,
        mode="quiz", user_input=_format_qa(questions, payload.answers), questions=questions,
        result=result, today=payload.today,
    )


@router.post("/tasks/{task_id}/master", response_model=TaskOut)
def master_task_endpoint(
    task_id: int,
    payload: MasterTaskRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> Task:
    """「我已掌握」：用户最终决定权，直接标 mastered（不依赖 LLM，AI 缺席兜底）。

    写一条 engine='manual' 的留痕，保证「真掌握率」有据可查、历史完整。
    """
    task = require_owned(db, Task, task_id, user_id)
    _require_learn(task)
    journey = _latest_active_journey(db, user_id)
    _mark_mastered(task)
    db.add(
        MasteryCheck(
            user_id=user_id,
            journey_id=journey.id if journey is not None else None,
            analysis_run_id=journey.analysis_run_id if journey is not None else None,
            task_id=task.id,
            mode="feynman",
            verdict="",
            passed=True,
            feedback="用户自评已掌握",
            engine="manual",
        )
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[MasteryCheckOut])
def list_mastery_checks(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[MasteryCheck]:
    """按时间倒序列出本用户的判定记录（回看）。"""
    stmt = scope_to_user(select(MasteryCheck), MasteryCheck, user_id).order_by(
        MasteryCheck.id.desc()
    )
    return list(db.scalars(stmt).all())
