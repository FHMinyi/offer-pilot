"""JD 导入路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import JobPosting
from ..schemas import JobImportRequest, JobOut
from ..services import jd_parser

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/import", response_model=list[JobOut])
def import_jobs(payload: JobImportRequest, db: Session = Depends(get_db)) -> list[JobPosting]:
    """批量导入并解析 JD（MVP 支持手动粘贴）。"""
    created: list[JobPosting] = []
    for item in payload.jobs:
        structured = jd_parser.parse_jd(item.raw_text)
        job = JobPosting(
            title=structured.get("title", ""),
            company=structured.get("company", ""),
            raw_text=item.raw_text,
            structured=structured,
            source_url=item.source_url,
        )
        db.add(job)
        created.append(job)
    db.commit()
    for job in created:
        db.refresh(job)
    return created
