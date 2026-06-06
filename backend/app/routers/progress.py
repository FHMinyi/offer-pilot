"""进度聚合路由（里程碑一）：实时聚合 Task + 惰性算 streak，无 scheduler。

对齐硬约束「lifespan 仅 init_db、无 cron」：streak 不建表、不预计算，每次请求即时
按 CheckIn 日期连续性惰性求得。单用户聚合成本可忽略。
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import CheckIn, JourneyState, Task
from ..ownership import scope_to_user
from ..schemas import ProgressOut, WeekProgressItem

router = APIRouter(prefix="/api/progress", tags=["progress"])


def _streaks(dates: list[date], today: date) -> tuple[int, int]:
    """由升序去重日期列表算 (current_streak, longest_streak)。

    current：从今天（或昨天，容忍当天未打卡）往回数连续日；都不连则 0。
    longest：扫一遍求最长连续段。
    """
    if not dates:
        return 0, 0
    dateset = set(dates)

    longest = 1
    run = 1
    for prev, cur in zip(dates, dates[1:]):
        if cur - prev == timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    anchor: date | None = None
    if today in dateset:
        anchor = today
    elif (today - timedelta(days=1)) in dateset:
        anchor = today - timedelta(days=1)

    current = 0
    if anchor is not None:
        d = anchor
        while d in dateset:
            current += 1
            d -= timedelta(days=1)
    return current, longest


@router.get("", response_model=ProgressOut)
def get_progress(
    journey_id: int | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> ProgressOut:
    """聚合当前旅程任务完成度 + 打卡 streak；空库返回零值（不报错）。"""
    # 解析旅程：指定 journey_id 优先，否则取最新 active（scope_to_user 本期放行）
    if journey_id is not None:
        journey = db.get(JourneyState, journey_id)
    else:
        jstmt = scope_to_user(
            select(JourneyState).where(JourneyState.status == "active"),
            JourneyState,
            user_id,
        ).order_by(JourneyState.id.desc())
        journey = db.scalars(jstmt).first()

    # 任务集：旅程绑定的 run 优先，排除软删 skipped
    tstmt = select(Task).where(Task.status != "skipped")
    if journey is not None and journey.analysis_run_id is not None:
        tstmt = tstmt.where(Task.analysis_run_id == journey.analysis_run_id)
    tstmt = scope_to_user(tstmt, Task, user_id)
    tasks = list(db.scalars(tstmt).all())

    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    completion_rate = (done / total) if total else 0.0

    week_map: dict[int, dict[str, int]] = {}
    for t in tasks:
        slot = week_map.setdefault(t.week, {"total": 0, "done": 0})
        slot["total"] += 1
        if t.status == "done":
            slot["done"] += 1
    week_progress = [
        WeekProgressItem(week=w, total=v["total"], done=v["done"])
        for w, v in sorted(week_map.items())
    ]

    # 打卡序列（scope_to_user 本期放行）
    cistmt = scope_to_user(select(CheckIn.date), CheckIn, user_id)
    dates = sorted({d for d in db.scalars(cistmt).all()})

    today = date.today()
    current_streak, longest_streak = _streaks(dates, today)
    last_checkin_date = dates[-1] if dates else None
    checked_in_today = today in set(dates)

    # current_week：有 start_date 按自然周推算，否则取旅程登记值
    if journey is not None and journey.start_date is not None:
        raw = (today - journey.start_date).days // 7 + 1
        current_week = max(1, min(raw, journey.planned_weeks or 1))
    elif journey is not None:
        current_week = journey.current_week or 1
    else:
        current_week = 1

    return ProgressOut(
        total_tasks=total,
        done_tasks=done,
        completion_rate=completion_rate,
        current_week=current_week,
        week_progress=week_progress,
        current_streak=current_streak,
        longest_streak=longest_streak,
        last_checkin_date=last_checkin_date,
        checked_in_today=checked_in_today,
    )
