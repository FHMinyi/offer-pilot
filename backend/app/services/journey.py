"""旅程主表的幂等维护（里程碑一：单用户取最新 active 一行）。

`ensure_journey` 是 JourneyState 的唯一写入收口：按 user_id 取最新 active，无则建，
并把活跃旅程指向最新一次分析。C2 为服务层纯逻辑、不接路由；C4 在 analysis.run_analysis
与 agent generate_plan 分支 commit 后旁路调用，物化 Task 前先确保有 journey 归属。
"""

from __future__ import annotations

from sqlalchemy import select

from ..models import AnalysisRun, JourneyState


def ensure_journey(db, run: AnalysisRun, user_id: str = "local") -> JourneyState:
    """取该 user 最新 active 旅程；无则新建。幂等单条，指向最新分析 run。"""
    journey = db.scalars(
        select(JourneyState)
        .where(JourneyState.user_id == user_id, JourneyState.status == "active")
        .order_by(JourneyState.id.desc())
    ).first()

    if journey is None:
        journey = JourneyState(
            user_id=user_id,
            analysis_run_id=run.id,
            target_role=run.target_role or "",
            planned_weeks=run.weeks or 4,
            # 自然日起算（C4）；首次设定后不再被覆盖，保 streak/planned_date 锚点稳定
            start_date=run.created_at.date() if run.created_at is not None else None,
        )
        db.add(journey)
    else:
        # 幂等更新：活跃旅程跟随最新一次分析（里程碑二再规划在此之上写）
        journey.analysis_run_id = run.id
        if run.target_role:
            journey.target_role = run.target_role
        if run.weeks:
            journey.planned_weeks = run.weeks
        if journey.start_date is None and run.created_at is not None:
            journey.start_date = run.created_at.date()

    db.commit()
    db.refresh(journey)
    return journey
