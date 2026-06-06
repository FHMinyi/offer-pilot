"""Pydantic 请求 / 响应模型。

设计原则（呼应 PRD §12.2）：输入尽量结构化，输出尽量可解释，
每个结论都尽量带来源说明。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from datetime import date as DateField  # 别名：供字段名为 date 的模型引用，避免被字段遮蔽
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _as_utc_iso(value: datetime) -> str:
    """把时间统一序列化为带时区的 UTC ISO 字符串。

    数据库（SQLite）取回的是“UTC 墙钟但不带时区”的 naive datetime，
    若直接输出会被前端 new Date() 当成本地时间，导致显示时间差一个时区偏移。
    这里补上 UTC 时区，前端即可正确换算到浏览器本地时间。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# 用于所有响应里的时间字段：序列化为带 +00:00 的 UTC，便于前端正确本地化
UtcDateTime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str, when_used="json")]

# ---------------------------------------------------------------------------
# 简历
# ---------------------------------------------------------------------------


class ResumeParseRequest(BaseModel):
    """粘贴文本解析简历。"""

    raw_text: str = Field(..., min_length=1, description="简历原始文本")


class ResumeOut(BaseModel):
    id: int
    raw_text: str
    structured: dict
    source_type: str
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# JD
# ---------------------------------------------------------------------------


class JobImportItem(BaseModel):
    raw_text: str = Field(..., min_length=1, description="单条 JD 原始文本")
    source_url: str = ""


class JobImportRequest(BaseModel):
    jobs: list[JobImportItem] = Field(..., min_length=1, description="待导入的 JD 列表")


class JobOut(BaseModel):
    id: int
    title: str
    company: str
    raw_text: str
    structured: dict
    source_url: str
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------


class AnalysisRunRequest(BaseModel):
    """运行一次完整分析。

    支持两种用法：
    1. 直接内联传入 resume_text + jd_texts（前端一键流程，推荐）；
    2. 传入已存在的 resume_id + job_ids（复用历史数据）。
    """

    resume_text: str | None = Field(None, description="简历文本（内联模式）")
    jd_texts: list[str] | None = Field(None, description="JD 文本列表（内联模式）")

    resume_id: int | None = Field(None, description="已存在的简历 id（引用模式）")
    job_ids: list[int] | None = Field(None, description="已存在的 JD id 列表（引用模式）")

    target_role: str = Field("", description="目标岗位方向，例如“前端实习”")
    weeks: int = Field(4, ge=1, le=12, description="学习路线周数")
    prefer_structured: bool = Field(
        True, description="引用模式优先复用 Resume.structured，缺失才回退重解析"
    )


class AnalysisRunOut(BaseModel):
    id: int
    resume_id: int
    job_ids: list[int]
    target_role: str
    weeks: int
    match_score: int
    engine: str
    result: dict
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 对话 Agent
# ---------------------------------------------------------------------------


class ChatMessageIn(BaseModel):
    role: str = Field(..., description="user 或 assistant")
    content: str = ""


class ChatContextIn(BaseModel):
    resume_text: str = ""
    jd_texts: list[str] = Field(default_factory=list)
    target_role: str = ""
    weeks: int = Field(4, ge=1, le=12)
    # 最近一次匹配分析的 id（前端收到 report 后回传），用于第二步 generate_plan 跨轮定位
    analysis_run_id: int | None = None
    # E3 人设引擎（B5）：语气强度 0=最温柔…100=最严格；persona 预留三人设键
    tone: int = Field(50, ge=0, le=100, description="语气强度 0=最温柔…100=最严格")
    persona: str = Field("default", description="人设键（B5 预留 coach/senior/butler）")


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(default_factory=list, description="对话历史")
    context: ChatContextIn = Field(default_factory=ChatContextIn, description="已收集的简历/JD/设置")
    # 思考强度：off/low/medium/high/xhigh/max（对支持推理的模型生效）
    reasoning_effort: str = "medium"
    # 前端传入的当前本地时间（让 AI 知道“现在”，避免检索过时年份）
    client_time: str = ""


# ---------------------------------------------------------------------------
# 会话（完整对话历史）
# ---------------------------------------------------------------------------


class ConversationSaveRequest(BaseModel):
    """新建或更新会话（id 为空=新建）。turns 为前端渲染消息数组，原样存取。"""

    id: int | None = None
    title: str = ""
    turns: list = Field(default_factory=list)
    # 会话上下文（简历/JD/目标岗位等），用于续聊恢复
    context: dict = Field(default_factory=dict)


class ConversationSaveOut(BaseModel):
    id: int
    title: str
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class ConversationOut(BaseModel):
    id: int
    title: str
    turns: list
    context: dict = Field(default_factory=dict)
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class ConversationSummaryOut(BaseModel):
    id: int
    title: str
    turn_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


# ---------------------------------------------------------------------------
# 可复用 JD 库
# ---------------------------------------------------------------------------


class SavedJdIn(BaseModel):
    title: str = ""
    content: str = Field(..., min_length=1, description="JD 原文")


class SavedJdOut(BaseModel):
    id: int
    title: str
    content: str
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class AnalysisSummaryOut(BaseModel):
    """历史列表中的精简表示。"""

    id: int
    target_role: str
    match_score: int
    engine: str
    job_count: int
    created_at: UtcDateTime


# ---------------------------------------------------------------------------
# 里程碑一 · 有状态闭环（任务 / 打卡 / 旅程 / 进度）
# ---------------------------------------------------------------------------

TaskStatus = Literal["todo", "doing", "done", "skipped"]
TaskKind = Literal["learn", "deliverable", "interview", "review"]
# C2 裁决统一：diagnosing/executing/applying/interviewing/closing
JourneyStage = Literal["diagnosing", "executing", "applying", "interviewing", "closing"]


class TaskOut(BaseModel):
    id: int
    user_id: str
    journey_id: int | None = None
    analysis_run_id: int
    week: int
    order_index: int
    skill_key: str
    title: str
    kind: TaskKind
    weight: int
    status: TaskStatus
    done: bool = False  # 便利冗余字段 =(status=='done')，由 Task.done 属性提供
    planned_date: date | None = None
    done_at: UtcDateTime | None = None
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class JourneyOut(BaseModel):
    id: int
    target_role: str
    analysis_run_id: int | None = None
    stage: JourneyStage
    status: str
    start_date: date | None = None
    planned_weeks: int
    current_week: int
    signals: dict = Field(default_factory=dict)  # E1.2 再规划信号(progress_health/carried_over…)
    last_replanned_at: UtcDateTime | None = None  # 最近一次动态重排时间
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class WeekProgressItem(BaseModel):
    week: int
    total: int
    done: int


class RecentDayItem(BaseModel):
    """最近 N 天打卡热力的单元（E4 坚持天数可视化）：旧→今排列。"""

    date: DateField
    checked: bool


class ProgressOut(BaseModel):
    total_tasks: int
    done_tasks: int
    completion_rate: float  # 0~1
    current_week: int
    week_progress: list[WeekProgressItem]
    current_streak: int
    longest_streak: int
    last_checkin_date: date | None = None
    checked_in_today: bool
    # E4 坚持天数可视化：最近 7 个自然日的打卡热力（旧→今，末位为今天）
    recent_days: list[RecentDayItem] = Field(default_factory=list)


class TaskPatchRequest(BaseModel):
    status: TaskStatus | None = None
    weight: int | None = Field(None, ge=0, le=10)  # 里程碑二降权靶点
    planned_date: date | None = None


class CheckInSaveRequest(BaseModel):
    # 字段名 date 与 datetime.date 同名：用别名 DateField 标注，避免 future-annotations 下遮蔽
    date: DateField | None = None  # 缺省=服务器当日；前端通常传本地自然日
    mood: str = ""
    note: str = Field("", description="一句话总结")
    minutes: int = Field(0, ge=0, le=1440)
    completed_task_ids: list[int] = Field(default_factory=list)


class CheckInOut(BaseModel):
    id: int
    date: DateField
    mood: str
    note: str
    minutes: int
    completed_task_ids: list[int]
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class JourneyPatchRequest(BaseModel):
    stage: JourneyStage | None = None
    target_role: str | None = None
    planned_weeks: int | None = Field(None, ge=1, le=12)
    current_week: int | None = Field(None, ge=1, le=12)


class ReplanRequest(BaseModel):
    settle: bool = Field(False, description="是否按每日结算降权逾期任务（结算按钮传 true）")
    today: DateField | None = Field(None, description="缺省=服务器当日；前端通常传本地自然日")


class ReplanOut(BaseModel):
    journey: JourneyOut
    tasks: list[TaskOut]


# ---------------------------------------------------------------------------
# 轨道 F1 · 面经复盘 → 盲区提取 → 权重回灌
# ---------------------------------------------------------------------------

BlindSpotSeverity = Literal["high", "mid", "low"]


class BlindSpotItem(BaseModel):
    """一条面试盲区：归一到技能本体的薄弱/被问倒技能。"""

    skill_key: str
    skill_name: str
    severity: BlindSpotSeverity = "mid"
    evidence: list[str] = Field(default_factory=list, description="命中的原始词/被问到的点")
    matched: bool = False  # 是否命中当前计划中的任务（命中则已被权重回灌）


class InterviewLogCreate(BaseModel):
    content: str = Field(..., min_length=1, description="面经/复盘原文")
    company: str = ""
    role: str = Field("", description="面试岗位/方向")
    # 客户端本地自然日；回灌时把命中任务的 planned_date 拉到这一天（进入「今日任务」）
    today: DateField | None = None


class InterviewLogOut(BaseModel):
    id: int
    company: str
    role: str
    content: str
    blind_spots: list[BlindSpotItem] = Field(default_factory=list)
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class InterviewReplayOut(BaseModel):
    """提交面经的回包：复盘记录 + 被回灌的任务 + 计划未覆盖的盲区（建议加练）。"""

    interview: InterviewLogOut
    boosted_tasks: list[TaskOut] = Field(default_factory=list)
    unmatched_skills: list[BlindSpotItem] = Field(default_factory=list)
