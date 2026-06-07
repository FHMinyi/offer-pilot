"""任务路由：roadmap 物化出的可勾选任务（里程碑一）。

C3 只读（GET 列表）；C4 追加 PATCH。归属经 deps.get_current_user，越权收窄由
ownership.scope_to_user 单点承载（本期放行：foo 与无头读到同一份数据）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Task
from ..ownership import require_owned, scope_to_user
from ..schemas import TaskOut, TaskPatchRequest

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    analysis_run_id: int | None = None,
    journey_id: int | None = None,
    week: int | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[Task]:
    """按 (week, order_index) 升序返回任务；支持按 run / journey / week 过滤。"""
    stmt = select(Task)
    if analysis_run_id is not None:
        stmt = stmt.where(Task.analysis_run_id == analysis_run_id)
    if journey_id is not None:
        stmt = stmt.where(Task.journey_id == journey_id)
    if week is not None:
        stmt = stmt.where(Task.week == week)
    stmt = scope_to_user(stmt, Task, user_id)  # 本期放行
    stmt = stmt.order_by(Task.week.asc(), Task.order_index.asc())
    return list(db.scalars(stmt).all())


@router.patch("/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: int,
    payload: TaskPatchRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> Task:
    """更新单个任务：status=done 写 done_at、非 done 清空；可改 weight/planned_date。

    只更新 Task，streak 留 GET /progress 惰性算（降耦合）。
    """
    task = require_owned(db, Task, task_id, user_id)
    if payload.status is not None:
        task.status = payload.status
        if payload.status == "done":
            task.done_at = task.done_at or datetime.now(timezone.utc)
        else:
            task.done_at = None
            # mastered 隐含 done：取消完成则一并降级掌握态，避免「未完成却 mastered」脏态
            task.mastery = "unknown"
            task.mastered_at = None
    if payload.weight is not None:
        task.weight = payload.weight
    if payload.planned_date is not None:
        task.planned_date = payload.planned_date
    db.commit()
    db.refresh(task)
    return task
