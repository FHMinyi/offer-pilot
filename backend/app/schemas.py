"""Pydantic 请求 / 响应模型。

设计原则（呼应 PRD §12.2）：输入尽量结构化，输出尽量可解释，
每个结论都尽量带来源说明。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

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
