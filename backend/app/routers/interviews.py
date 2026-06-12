"""面经复盘路由（轨道 F1）：提交面经 → 提盲区 → 权重回灌；列表回看。

闭环输入端。提交后：抽盲区（LLM/规则）→ 存 InterviewLog → 对当前活跃旅程的任务做
权重回灌（命中盲区的未完成任务提 weight + 拉到今天）→ 回包带「被回灌的任务」与
「计划未覆盖的盲区（建议加练）」。无活跃旅程时只存面经、不回灌。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import AnalysisRun, InterviewLog, JourneyState
from ..ownership import scope_to_user
from ..schemas import (
    BlindSpotItem,
    InterviewLogCreate,
    InterviewLogOut,
    InterviewReplayOut,
    TaskOut,
)
from ..services.interview import extract_blind_spots, reweight_from_blind_spots
from ..services.usage import usage_context

logger = logging.getLogger("offerpilot.interviews")

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _latest_active_journey(db: Session, user_id: str) -> JourneyState | None:
    stmt = scope_to_user(
        select(JourneyState).where(JourneyState.status == "active"),
        JourneyState,
        user_id,
    ).order_by(JourneyState.id.desc())
    return db.scalars(stmt).first()


@router.post("", response_model=InterviewReplayOut)
def create_interview(
    payload: InterviewLogCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> InterviewReplayOut:
    """提交一次面经复盘：抽盲区、存档、权重回灌，返回回灌结果与建议加练项。"""
    journey = _latest_active_journey(db, user_id)
    run = None
    if journey is not None and journey.analysis_run_id is not None:
        run = db.get(AnalysisRun, journey.analysis_run_id)

    with usage_context(
        path="blindspot",
        user_id=user_id,
        analysis_run_id=journey.analysis_run_id if journey is not None else None,
    ):
        spots = extract_blind_spots(payload.content, run)

    log = InterviewLog(
        user_id=user_id,
        journey_id=journey.id if journey is not None else None,
        analysis_run_id=journey.analysis_run_id if journey is not None else None,
        company=payload.company or "",
        role=payload.role or "",
        content=payload.content,
        blind_spots=spots,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    boosted: list = []
    matched_keys: set[str] = set()
    if journey is not None:
        try:
            res = reweight_from_blind_spots(db, journey, spots, today=payload.today)
            boosted = res["boosted"]
            matched_keys = res["matched_keys"]
            # matched 回填与回灌的任务改动在同一事务里一次提交：任一步失败 rollback 可整体回退，
            # 避免「任务已落库改动、响应却说没回灌」的不一致（面经本体已在上面单独提交，不受影响）。
            for s in spots:
                s["matched"] = s["skill_key"] in matched_keys
            log.blind_spots = list(spots)  # 重新赋值触发 JSON 字段变更检测
            db.commit()
            db.refresh(log)
        except Exception:  # noqa: BLE001 回灌失败不连累已存面经，但要留痕（否则线上静默失败难定位）
            logger.exception("面经权重回灌失败，已回滚（面经本体已保存）")
            db.rollback()
            boosted, matched_keys = [], set()

    # 以实际落库的 blind_spots 计算未覆盖盲区（无旅程/回灌回滚时 matched 均为 False）
    unmatched = [s for s in (log.blind_spots or []) if not s.get("matched")]
    return InterviewReplayOut(
        interview=InterviewLogOut.model_validate(log),
        boosted_tasks=[TaskOut.model_validate(t) for t in boosted],
        unmatched_skills=[BlindSpotItem.model_validate(s) for s in unmatched],
    )


@router.get("", response_model=list[InterviewLogOut])
def list_interviews(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[InterviewLog]:
    """按时间倒序列出本用户的面经复盘记录。"""
    stmt = scope_to_user(select(InterviewLog), InterviewLog, user_id).order_by(
        InterviewLog.id.desc()
    )
    return list(db.scalars(stmt).all())
