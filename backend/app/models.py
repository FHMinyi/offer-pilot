"""ORM 模型：MVP 阶段只保留闭环必需的三张核心表。

为降低复杂度，结构化解析结果统一以 JSON 字段存储，
避免一开始就拆出 ProjectExperience / SkillNode 等多张关联表。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    """简历：保存原始文本与结构化解析结果。"""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 结构化解析结果（基本信息/教育/项目/技能/证据片段等）
    structured: Mapped[dict] = mapped_column(JSON, default=dict)
    # 来源类型：paste / pdf
    source_type: Mapped[str] = mapped_column(String(16), default="paste")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class JobPosting(Base):
    """目标岗位 JD：保存原始文本与结构化解析结果。"""

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AnalysisRun(Base):
    """一次完整分析：关联简历与一组 JD，保存完整分析结果以支持历史回看。"""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), nullable=False)
    # 关联的 JD id 列表
    job_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 目标岗位方向，例如“前端实习”
    target_role: Mapped[str] = mapped_column(String(255), default="")
    weeks: Mapped[int] = mapped_column(Integer, default=4)
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    # 完整分析结果（缺口/优化建议/路线/来源说明等）
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # 标记本次分析使用的解析模式：llm:openai / llm:anthropic / rule
    engine: Mapped[str] = mapped_column(String(32), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    resume: Mapped[Resume] = relationship("Resume")


class Conversation(Base):
    """完整对话记录：保存渲染用的有序消息（含报告块），支持历史回看。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    # 前端渲染用的消息数组（user/assistant 的有序 blocks），整体以 JSON 存储
    turns: Mapped[list] = mapped_column(JSON, default=list)
    # 会话上下文（简历/JD/目标岗位/周数/最近分析 id），用于续聊时恢复、保存相关职位 JD 作参考
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SavedJd(Base):
    """可复用的测试 JD：保存从招聘网站复制的 JD，便于下次直接使用。"""

    __tablename__ = "saved_jds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
