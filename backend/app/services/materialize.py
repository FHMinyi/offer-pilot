"""roadmap → Task 幂等物化契约（里程碑一最大风险点的治理）。

把 `AnalysisRun.result["roadmap"]`（确定性纯函数 roadmap.generate 的产物，每个
WeekItem 含 week / focus_skills / tasks / deliverables / interview_focus /
estimated_hours）拆成可勾选的 Task 行。本模块是服务层纯逻辑，C2 不接路由，
C4 才在主链 commit 后旁路调用（try 包裹、失败降级「有报告无 Task」）。

==============================  物化契约（务必稳定）  ==========================
1. 拆分：每个 WeekItem 内
     tasks[i]          → kind="learn"
     deliverables[i]   → kind="deliverable"
     interview_focus[i]→ kind="interview"
2. order_index：在「该 run 该 week」内**跨 kind 从 0 连续编号**（先 learn、再
   deliverable、后 interview），作为物化幂等业务键 + 周内稳定排序。
3. 字段：title=裸字符串；skill_key=该 week focus_skills[0]（roadmap 不暴露技能 key，
   故存其名，截断 64；无则 ""）；weight=1；
   planned_date = (journey.start_date or run.created_at.date()) + (week-1)*7。
4. 幂等 merge-upsert（业务键 = (analysis_run_id, week, order_index)）：
     命中 → 更新展示性字段(title/kind/skill_key/planned_date)，**保留用户进度
            (status=done/doing 与 done_at)**；若旧行是系统软删的 skipped 且本次又
            出现在 roadmap，则**复活为 todo**（skipped 是系统软删、非用户进度）。
     未命中 → 新建 status="todo"。
     roadmap 删去且非 done 的旧 Task → 标 status="skipped"（软删不物删，保证
            CheckIn.completed_task_ids 引用永不悬空）。

==============================  里程碑二接缝（显式记账）  =======================
本契约只覆盖「**同一 run_id** 重跑 generate_plan」（调周数/换偏好）。order_index 是
**位置对账**而非语义对账：weeks 变化会令 roadmap 重新分配技能，同一 (week,order_index)
的内容可能换成别的技能，此时已 done 的行按位置保留 done（里程碑一接受的取舍）。
「**换 JD / 重新 analyze 产生新 run_id**」时旧 run 的 Task 如何迁移到新 run，本期
**不实现**，留作里程碑二一等待办（按 skill_key/title 模糊对齐 + 平移已 done /
被 CheckIn 引用的 Task）。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from ..models import AnalysisRun, JourneyState, Task

# (kind, WeekItem 字段名) —— 顺序即 order_index 的跨 kind 连续编号顺序
_KIND_FIELDS: tuple[tuple[str, str], ...] = (
    ("learn", "tasks"),
    ("deliverable", "deliverables"),
    ("interview", "interview_focus"),
)


def materialize_tasks(
    db,
    run: AnalysisRun,
    user_id: str = "local",
    journey: JourneyState | None = None,
) -> list[Task]:
    """把 run.result['roadmap'] 幂等物化为 Task 行，返回本次活跃（非软删）Task 列表。"""
    roadmap = (run.result or {}).get("roadmap") or []
    base_date = None
    if journey is not None and journey.start_date is not None:
        base_date = journey.start_date
    elif run.created_at is not None:
        base_date = run.created_at.date()

    existing_rows = db.scalars(
        select(Task).where(Task.analysis_run_id == run.id)
    ).all()
    existing = {(t.week, t.order_index): t for t in existing_rows}

    seen: set[tuple[int, int]] = set()
    active: list[Task] = []

    for week_item in roadmap:
        week = int(week_item.get("week", 1))
        focus = week_item.get("focus_skills") or []
        skill_key = (str(focus[0])[:64] if focus else "")
        planned = base_date + timedelta(days=(week - 1) * 7) if base_date else None

        order_index = 0
        for kind, field in _KIND_FIELDS:
            for raw_title in (week_item.get(field) or []):
                title = str(raw_title)
                key = (week, order_index)
                seen.add(key)
                row = existing.get(key)
                if row is None:
                    row = Task(
                        user_id=user_id,
                        journey_id=journey.id if journey is not None else None,
                        analysis_run_id=run.id,
                        week=week,
                        order_index=order_index,
                        skill_key=skill_key,
                        title=title,
                        kind=kind,
                        weight=1,
                        status="todo",
                        planned_date=planned,
                    )
                    db.add(row)
                else:
                    # 命中：更新展示性字段，保留用户进度（done/doing + done_at）
                    row.title = title
                    row.kind = kind
                    row.skill_key = skill_key
                    row.planned_date = planned
                    if journey is not None and row.journey_id is None:
                        row.journey_id = journey.id
                    # 系统软删过、本次又回到 roadmap → 复活（非用户进度）
                    if row.status == "skipped":
                        row.status = "todo"
                active.append(row)
                order_index += 1

    # roadmap 删去且非 done 的旧 Task → 软删 skipped（保证 CheckIn 引用不悬空）
    for key, row in existing.items():
        if key not in seen and row.status != "done":
            row.status = "skipped"

    db.commit()
    for row in active:
        db.refresh(row)
    return active
