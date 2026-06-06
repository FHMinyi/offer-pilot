"""每日打卡路由（里程碑一）：upsert（同 user_id+date 覆盖）+ 列表。

对齐 conversations 的 upsert 风格；写路径按 user_id 归属（满足 UNIQUE(user_id,date)），
读路径经 ownership.scope_to_user（本期放行）。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import CheckIn, JourneyState
from ..ownership import scope_to_user
from ..schemas import CheckInOut, CheckInSaveRequest
from ..services.replan import replan_journey

router = APIRouter(prefix="/api/checkins", tags=["checkins"])


@router.post("", response_model=CheckInOut)
def upsert_checkin(
    payload: CheckInSaveRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> CheckIn:
    """新建或覆盖当日打卡（同 user_id+date 唯一）。date 缺省=服务器当日。"""
    the_date = payload.date or date.today()
    row = db.scalars(
        select(CheckIn).where(CheckIn.user_id == user_id, CheckIn.date == the_date)
    ).first()
    if row is None:
        row = CheckIn(
            user_id=user_id,
            date=the_date,
            mood=payload.mood,
            note=payload.note,
            minutes=payload.minutes,
            completed_task_ids=payload.completed_task_ids,
        )
        db.add(row)
    else:
        row.mood = payload.mood
        row.note = payload.note
        row.minutes = payload.minutes
        row.completed_task_ids = payload.completed_task_ids
    db.commit()
    db.refresh(row)

    # 打卡=每日结算：自动按进度顺延/重组剩余日程（失败不影响打卡本身）
    try:
        journey = db.scalars(
            select(JourneyState)
            .where(JourneyState.user_id == user_id, JourneyState.status == "active")
            .order_by(JourneyState.id.desc())
        ).first()
        if journey is not None:
            replan_journey(db, journey, today=the_date, settle=True)
    except Exception:  # noqa: BLE001
        db.rollback()

    return row


@router.get("", response_model=list[CheckInOut])
def list_checkins(
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[CheckIn]:
    """按 date 倒序返回打卡；可选 start/end 闭区间过滤。"""
    stmt = select(CheckIn)
    if start is not None:
        stmt = stmt.where(CheckIn.date >= start)
    if end is not None:
        stmt = stmt.where(CheckIn.date <= end)
    stmt = scope_to_user(stmt, CheckIn, user_id).order_by(CheckIn.date.desc())
    return list(db.scalars(stmt).all())
