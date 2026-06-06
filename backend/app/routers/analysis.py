"""分析路由：运行分析、查询历史（PRD §12）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import AnalysisRun, JobPosting, Resume
from ..schemas import AnalysisRunOut, AnalysisRunRequest, AnalysisSummaryOut
from ..services import pipeline
from ..services.journey import ensure_journey
from ..services.materialize import materialize_tasks

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/run", response_model=AnalysisRunOut)
def run_analysis(
    payload: AnalysisRunRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> AnalysisRun:
    """运行一次完整分析并保存结果。

    支持内联模式（resume_text + jd_texts）与引用模式（resume_id + job_ids）。
    """
    resume_text, resume_row = _resolve_resume(payload, db)
    jd_texts, job_rows = _resolve_jobs(payload, db)

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="缺少简历内容：请提供 resume_text 或有效的 resume_id。")
    if not jd_texts:
        raise HTTPException(status_code=400, detail="缺少 JD：请提供 jd_texts 或有效的 job_ids。")

    # 引用模式复用已有 Resume.structured，跳过简历重解析（缺失或关闭则回退）
    resume_structured = (
        resume_row.structured
        if (payload.prefer_structured and resume_row is not None and resume_row.structured)
        else None
    )

    outcome = pipeline.run_analysis(
        resume_text=resume_text,
        jd_texts=jd_texts,
        target_role=payload.target_role,
        weeks=payload.weeks,
        resume_structured=resume_structured,
    )

    # 内联模式下新建 Resume / JobPosting 行，复用 pipeline 已解析的结构化结果
    if resume_row is None:
        resume_row = Resume(
            raw_text=resume_text,
            structured=outcome["resume"],
            source_type="paste",
        )
        db.add(resume_row)
        db.flush()

    if not job_rows:
        for raw, structured in zip(jd_texts, outcome["parsed_jds"]):
            job = JobPosting(
                title=structured.get("title", ""),
                company=structured.get("company", ""),
                raw_text=raw,
                structured=structured,
            )
            db.add(job)
            job_rows.append(job)
        db.flush()

    run = AnalysisRun(
        resume_id=resume_row.id,
        job_ids=[j.id for j in job_rows],
        target_role=payload.target_role,
        weeks=payload.weeks,
        match_score=outcome["result"]["match_score"],
        result=outcome["result"],
        engine=outcome["engine"],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 物化有状态闭环（旁路、失败降级「有报告无 Task」，不影响报告返回）
    try:
        journey = ensure_journey(db, run, user_id)
        materialize_tasks(db, run, user_id, journey)
    except Exception:  # noqa: BLE001
        db.rollback()

    return run


@router.get("", response_model=list[AnalysisSummaryOut])
def list_analyses(db: Session = Depends(get_db)) -> list[AnalysisSummaryOut]:
    """历史记录列表（按时间倒序）。"""
    rows = db.scalars(select(AnalysisRun).order_by(AnalysisRun.created_at.desc())).all()
    return [
        AnalysisSummaryOut(
            id=r.id,
            target_role=r.target_role,
            match_score=r.match_score,
            engine=r.engine,
            job_count=len(r.job_ids or []),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{analysis_id}", response_model=AnalysisRunOut)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)) -> AnalysisRun:
    """获取单次分析的完整结果。"""
    run = db.get(AnalysisRun, analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail="分析记录不存在。")
    return run


# ---------------------------------------------------------------------------
# 输入解析辅助
# ---------------------------------------------------------------------------


def _resolve_resume(payload: AnalysisRunRequest, db: Session) -> tuple[str, Resume | None]:
    if payload.resume_text and payload.resume_text.strip():
        return payload.resume_text, None
    if payload.resume_id is not None:
        resume = db.get(Resume, payload.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail=f"简历 {payload.resume_id} 不存在。")
        return resume.raw_text, resume
    return "", None


def _resolve_jobs(payload: AnalysisRunRequest, db: Session) -> tuple[list[str], list[JobPosting]]:
    if payload.jd_texts:
        texts = [t for t in payload.jd_texts if t and t.strip()]
        return texts, []
    if payload.job_ids:
        rows = [db.get(JobPosting, jid) for jid in payload.job_ids]
        missing = [jid for jid, row in zip(payload.job_ids, rows) if row is None]
        if missing:
            raise HTTPException(status_code=404, detail=f"JD 不存在：{missing}")
        valid = [r for r in rows if r is not None]
        return [r.raw_text for r in valid], valid
    return [], []
