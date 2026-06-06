"""旅程路由（里程碑一）：取最新 active 旅程。

C3 只读（GET）；C4 追加 PATCH（推进 stage / 改 target_role / weeks，里程碑二写入口）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import JourneyState
from ..ownership import require_owned, scope_to_user
from ..schemas import JourneyOut, JourneyPatchRequest

router = APIRouter(prefix="/api/journey", tags=["journey"])


@router.get("", response_model=JourneyOut)
def get_journey(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> JourneyState:
    """取最新 active 旅程；无则 404（前端据此引导先做匹配分析并生成计划）。"""
    stmt = scope_to_user(
        select(JourneyState).where(JourneyState.status == "active"),  # 本期放行
        JourneyState,
        user_id,
    ).order_by(JourneyState.id.desc())
    journey = db.scalars(stmt).first()
    if journey is None:
        raise HTTPException(
            status_code=404,
            detail="尚无进行中的旅程，请先完成一次匹配分析并生成计划。",
        )
    return journey


@router.patch("/{journey_id}", response_model=JourneyOut)
def patch_journey(
    journey_id: int,
    payload: JourneyPatchRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> JourneyState:
    """推进 stage / 改 target_role / planned_weeks / current_week（里程碑二写入口）。"""
    journey = require_owned(db, JourneyState, journey_id, user_id)
    if payload.stage is not None:
        journey.stage = payload.stage
    if payload.target_role is not None:
        journey.target_role = payload.target_role
    if payload.planned_weeks is not None:
        journey.planned_weeks = payload.planned_weeks
    if payload.current_week is not None:
        journey.current_week = payload.current_week
    db.commit()
    db.refresh(journey)
    return journey
