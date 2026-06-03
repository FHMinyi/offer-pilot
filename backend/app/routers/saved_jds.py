"""可复用 JD 库路由：保存/列出/编辑/删除测试用 JD。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SavedJd
from ..schemas import SavedJdIn, SavedJdOut

router = APIRouter(prefix="/api/saved-jds", tags=["saved_jds"])


def _title_of(payload: SavedJdIn) -> str:
    """标题为空时，用内容首行（截断）兜底。"""
    title = (payload.title or "").strip()
    if title:
        return title[:255]
    first_line = next((ln.strip() for ln in payload.content.splitlines() if ln.strip()), "未命名 JD")
    return first_line[:40]


@router.get("", response_model=list[SavedJdOut])
def list_saved_jds(db: Session = Depends(get_db)) -> list[SavedJd]:
    return list(db.scalars(select(SavedJd).order_by(SavedJd.updated_at.desc())).all())


@router.post("", response_model=SavedJdOut)
def create_saved_jd(payload: SavedJdIn, db: Session = Depends(get_db)) -> SavedJd:
    jd = SavedJd(title=_title_of(payload), content=payload.content)
    db.add(jd)
    db.commit()
    db.refresh(jd)
    return jd


@router.put("/{jd_id}", response_model=SavedJdOut)
def update_saved_jd(jd_id: int, payload: SavedJdIn, db: Session = Depends(get_db)) -> SavedJd:
    jd = db.get(SavedJd, jd_id)
    if jd is None:
        raise HTTPException(status_code=404, detail="JD 不存在。")
    jd.title = _title_of(payload)
    jd.content = payload.content
    db.commit()
    db.refresh(jd)
    return jd


@router.delete("/{jd_id}")
def delete_saved_jd(jd_id: int, db: Session = Depends(get_db)) -> dict:
    jd = db.get(SavedJd, jd_id)
    if jd is None:
        raise HTTPException(status_code=404, detail="JD 不存在。")
    db.delete(jd)
    db.commit()
    return {"ok": True}
