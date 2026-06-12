"""简历相关路由：粘贴解析与 PDF 上传解析。"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Resume
from ..schemas import ResumeOut, ResumeParseRequest
from ..services import resume_parser
from ..services.usage import usage_context

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.post("/parse", response_model=ResumeOut)
def parse_resume(
    payload: ResumeParseRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> Resume:
    """解析粘贴的简历文本并保存。"""
    with usage_context(path="resume", user_id=user_id):
        structured = resume_parser.parse_resume(payload.raw_text)
    resume = Resume(raw_text=payload.raw_text, structured=structured, source_type="paste")
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@router.post("/upload", response_model=ResumeOut)
def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> Resume:
    """上传 PDF 简历，抽取文本并解析保存。"""
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="目前仅支持 PDF 文件，其它格式请直接粘贴文本。")

    raw_bytes = file.file.read()
    text = _extract_pdf_text(raw_bytes)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="未能从 PDF 中提取到文本，可能是扫描件或图片型 PDF，请改用粘贴方式。",
        )

    with usage_context(path="resume", user_id=user_id):
        structured = resume_parser.parse_resume(text)
    resume = Resume(raw_text=text, structured=structured, source_type="pdf")
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


def _extract_pdf_text(raw_bytes: bytes) -> str:
    """用 pypdf 抽取 PDF 文本。"""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"PDF 解析失败：{exc}") from exc
