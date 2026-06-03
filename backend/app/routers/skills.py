"""技能图谱路由。"""

from __future__ import annotations

from fastapi import APIRouter

from ..services import skills as skills_svc

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/graph")
def skill_graph() -> dict:
    """返回技能图谱（树状 + 熟练度等级）。"""
    return skills_svc.build_graph()
