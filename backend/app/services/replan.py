"""动态再规划引擎（E1.2）：打卡/结算后按完成情况增量重排剩余日程。

**非从零重生成**——保留已完成进度，只对未完成任务做「顺延 + 重组（+ 结算降权）」：
- **顺延**：planned_date 早于今天且未完成的任务，滚动到今天起的剩余日程。
- **重组**：所有未完成任务（todo/doing）按 (week, order_index) 序，以每日容量上限
  均匀重排到 [今天 .. 计划末日]，避免逾期任务堆成一坨。
- **降权（仅 settle=True，即每日结算）**：本次仍逾期未完成的任务 weight−1（下限 0），
  作「持续被顺延」的至危信号，供前端弱化展示 / E2 状态机消费。

写入靶点字段（轨道 C 已建、本期可写、无需改表）：
`Task.planned_date/weight`、`JourneyState.last_replanned_at/current_week/signals`。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil

from sqlalchemy import select

from ..models import JourneyState, Task


def _horizon_dates(start: date | None, planned_weeks: int, today: date) -> list[date]:
    """剩余可排期日期：[今天 .. 计划末日]；计划已到期则给 3 天宽限收尾。"""
    if start is not None:
        end = start + timedelta(days=planned_weeks * 7 - 1)
    else:
        end = today + timedelta(days=planned_weeks * 7 - 1)
    if end < today:
        end = today + timedelta(days=2)
    n = (end - today).days + 1
    return [today + timedelta(days=i) for i in range(max(1, n))]


def replan_journey(
    db,
    journey: JourneyState,
    *,
    today: date | None = None,
    settle: bool = False,
) -> list[Task]:
    """对一条旅程的剩余任务做顺延+重组(+settle 降权)；返回该 run 全部活跃任务(含 done)。"""
    if today is None:
        today = date.today()
    run_id = journey.analysis_run_id
    if run_id is None:
        return []

    tasks = db.scalars(
        select(Task)
        .where(Task.analysis_run_id == run_id, Task.status != "skipped")
        .order_by(Task.week.asc(), Task.order_index.asc())
    ).all()
    remaining = [t for t in tasks if t.status in ("todo", "doing")]

    # 重排前先数有多少逾期未完成（用作降权依据 + 展示「顺延了几条」信号）
    carried = sum(
        1 for t in remaining if t.planned_date is not None and t.planned_date < today
    )

    # 降权：结算时仍逾期未完成 → 至危信号（capped 0）
    if settle:
        for t in remaining:
            if t.planned_date is not None and t.planned_date < today:
                t.weight = max(0, t.weight - 1)

    # 顺延 + 重组：按 (week, order_index) 序以每日容量把未完成任务摊到 [今天..末日]
    dates = _horizon_dates(journey.start_date, journey.planned_weeks or 1, today)
    if remaining:
        cap = max(1, ceil(len(remaining) / len(dates)))
        di = 0
        used = 0
        for t in remaining:
            if used >= cap and di < len(dates) - 1:
                di += 1
                used = 0
            t.planned_date = dates[di]
            used += 1

    # 更新旅程信号（供前端展示 + E2 状态机预留）
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    journey.signals = {
        **(journey.signals or {}),
        "progress_health": round(done / total, 3) if total else 0.0,
        "carried_over": carried,  # 本次顺延的逾期任务数
        "remaining": len(remaining),
    }
    if journey.start_date is not None:
        raw = (today - journey.start_date).days // 7 + 1
        journey.current_week = max(1, min(raw, journey.planned_weeks or 1))
    journey.last_replanned_at = datetime.now(timezone.utc)

    db.commit()
    for t in tasks:
        db.refresh(t)
    return tasks
