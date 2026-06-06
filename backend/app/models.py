"""ORM 模型：MVP 阶段只保留闭环必需的三张核心表。

为降低复杂度，结构化解析结果统一以 JSON 字段存储，
避免一开始就拆出 ProjectExperience / SkillNode 等多张关联表。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


# ---------------------------------------------------------------------------
# 里程碑一 · 有状态闭环三表（JourneyState / Task / CheckIn）。
# day-one 全带 user_id String(64)，与未来真实 id 同形（接缝见 app/deps.py）。
# 字段口径与 docs/方案_里程碑一_地基层_2026-06-05.md §3.2 一致，并已并入 B 轨决策
# （B2 profile_type / B3 signals+stage 派生 / B4 多终态 status / B5 persona+tone）。
# 现有 5 表零改动。
# ---------------------------------------------------------------------------


class JourneyState(Base):
    """旅程主表：单用户取最新 active 一行（约定，非约束）。"""

    __tablename__ = "journey_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="local")
    # B2 预留四类画像键(F3): student/newgrad/switcher/jobhopper
    profile_type: Mapped[str] = mapped_column(String(16), default="student")
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=True, index=True
    )
    target_role: Mapped[str] = mapped_column(String(255), default="")
    # B3 多维并存信号：真值是各独立信号，不再是单值线性 stage。
    #   M1 多数由 Task/CheckIn 实时派生(进度健康度/中断天数)，少数显式存这里(M3 写)。
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    # 派生展示标签(由 signals 组合算出，非线性真值):
    #   diagnosing/executing/applying/interviewing/closing
    stage: Mapped[str] = mapped_column(String(32), default="executing")
    # B4 多终态(取代原 active/archived): active/paused/succeeded/unmet/withdrawn
    status: Mapped[str] = mapped_column(String(16), default="active")
    # B5 单人设+滑块，预留三人设：persona 命名人格、tone 语气强度(鼓励⟷鞭策)
    persona: Mapped[str] = mapped_column(String(32), default="default")
    tone: Mapped[int] = mapped_column(Integer, default=50)  # 0=最温柔 … 100=最严格
    # 自然日(C4)，streak / planned_date 起算
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_weeks: Mapped[int] = mapped_column(Integer, default=4)
    current_week: Mapped[int] = mapped_column(Integer, default=1)  # 里程碑二靶点
    last_replanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # 里程碑二靶点
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="journey", cascade="all, delete-orphan"
    )


class Task(Base):
    """roadmap 物化为可勾选行——闭环核心 + 物化契约锚点。"""

    __tablename__ = "tasks"
    __table_args__ = (
        # C3 物化幂等业务键：周内跨 kind 连续编号
        UniqueConstraint("analysis_run_id", "week", "order_index", name="uq_task_run_week_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 稳定主键：CheckIn 引用它
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="local")
    journey_id: Mapped[int | None] = mapped_column(
        ForeignKey("journey_states.id"), nullable=True, index=True
    )
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=False, index=True
    )
    week: Mapped[int] = mapped_column(Integer, default=1)
    # 该 run 该 week 内跨 kind 连续序(C3)，物化幂等键 + 周内排序
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    skill_key: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 原 roadmap 裸字符串
    kind: Mapped[str] = mapped_column(String(16), default="learn")  # learn/deliverable/interview/review
    weight: Mapped[int] = mapped_column(Integer, default=1)  # 里程碑二重排/降权靶点
    status: Mapped[str] = mapped_column(String(16), default="todo")  # 四态 todo/doing/done/skipped
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    journey: Mapped["JourneyState | None"] = relationship("JourneyState", back_populates="tasks")

    @property
    def done(self) -> bool:
        """便利只读字段：完成判定统一 status=='done'（供 TaskOut 序列化，非数据库列）。"""
        return self.status == "done"


class CheckIn(Base):
    """每日打卡：同 user_id+date 唯一，upsert；引用 Task.id 稳定主键。"""

    __tablename__ = "check_ins"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_checkin_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="local")
    journey_id: Mapped[int | None] = mapped_column(
        ForeignKey("journey_states.id"), nullable=True, index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)  # 客户端本地自然日
    mood: Mapped[str] = mapped_column(String(16), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    # list[int]，引用 Task.id（非 week/index），稳定主键回指
    completed_task_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
