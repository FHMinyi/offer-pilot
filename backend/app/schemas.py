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


class LLMOverrideIn(BaseModel):
    """前端按会话自定义大语言模型（BYO LLM）：字段全部可选，空串=未设、回退服务端 .env。"""

    provider: str = ""        # openai / anthropic / ""(=用服务端)
    model: str = ""           # 默认档（对话/优化/面经/费曼/出题/判定）
    model_resume: str = ""    # 简历解析档（选填，空=回退默认/服务端）
    model_jd: str = ""        # JD 解析档（选填，空=回退默认/服务端）
    base_url: str = ""
    api_key: str = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(default_factory=list, description="对话历史")
    context: ChatContextIn = Field(default_factory=ChatContextIn, description="已收集的简历/JD/设置")
    # 思考强度：off/low/medium/high/xhigh/max（对支持推理的模型生效）
    reasoning_effort: str = "medium"
    # 前端传入的当前本地时间（让 AI 知道“现在”，避免检索过时年份）
    client_time: str = ""
    # 前端自定义大语言模型（BYO LLM）：按本次请求覆盖服务端 .env，空=用服务端
    llm_override: LLMOverrideIn | None = None


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
    # 双层状态第二层（仅 learn 类有意义）：mastery 字符串 + mastered 便利字段 =(mastery=='mastered')
    mastery: str = "unknown"  # 'unknown' | 'mastered'
    mastered: bool = False
    mastered_at: UtcDateTime | None = None
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
    # 双层状态：真掌握率（仅统计 learn 类）。done_tasks/completion_rate 口径不变，纯增量字段
    mastered_tasks: int = 0
    total_learn_tasks: int = 0
    mastery_rate: float = 0.0  # 0~1，= mastered_tasks / total_learn_tasks


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


# ---------------------------------------------------------------------------
# 费曼/出题判定学习掌握度（把校验前移到学习环节 · 复用 F1 的学习闭环引擎）
# ---------------------------------------------------------------------------

MasteryMode = Literal["feynman", "quiz"]
# 掌握度四档 + 空串（降级/自评时无 AI 评级）
MasteryVerdict = Literal["excellent", "good", "fair", "poor", ""]


class QuizQuestion(BaseModel):
    """出题模式 AI 出的一道题。"""

    q: str
    hint: str = ""  # 可选作答方向提示


class FeynmanJudgeRequest(BaseModel):
    """费曼模式：用户用自己的话复述某 learn 任务，提交判定。"""

    task_id: int
    content: str = Field(..., min_length=1, description="用户的费曼复述原文")
    # 命中缺口回灌时把任务 planned_date 拉到这一天（同 F1 口径）
    today: DateField | None = None
    # 判定类可选推理强度 off/low/medium/high/xhigh/max
    reasoning_effort: str = "medium"


class QuizGenerateRequest(BaseModel):
    """出题模式第一步：为某 learn 任务生成 2-3 道题。"""

    task_id: int
    # 判定类可选推理强度 off/low/medium/high/xhigh/max
    reasoning_effort: str = "medium"


class QuizGenerateOut(BaseModel):
    task_id: int
    questions: list[QuizQuestion] = Field(default_factory=list)
    available: bool = True  # False=未配置 LLM，前端引导走「我已掌握」手动标记


class QuizJudgeRequest(BaseModel):
    """出题模式第二步：提交答案判分（questions 由前端原样回传，无状态）。"""

    task_id: int
    questions: list[QuizQuestion] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    today: DateField | None = None
    # 判定类可选推理强度 off/low/medium/high/xhigh/max
    reasoning_effort: str = "medium"


class MasterTaskRequest(BaseModel):
    """「我已掌握」：用户最终决定权，直接标 mastered，不依赖 LLM。"""

    today: DateField | None = None


class MasteryCheckOut(BaseModel):
    """一条判定记录（可回看）。gaps 复用 F1 的 BlindSpotItem，印证同构。"""

    id: int
    task_id: int | None = None
    mode: MasteryMode = "feynman"
    verdict: MasteryVerdict = ""
    passed: bool = False
    feedback: str = ""
    followup_questions: list[str] = Field(default_factory=list)
    gaps: list[BlindSpotItem] = Field(default_factory=list)
    engine: str = "rule"
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class MasteryJudgeOut(BaseModel):
    """判定回包（仿 InterviewReplayOut）：判定记录 + 被判定任务 + 回灌任务 + 未覆盖缺口。"""

    check: MasteryCheckOut
    task: TaskOut  # 被判定的任务（含更新后的 mastery）
    available: bool = True  # 是否走了真实 AI 判定（False=降级，引导手动标记）
    boosted_tasks: list[TaskOut] = Field(default_factory=list)
    unmatched_skills: list[BlindSpotItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Token 用量统计子系统：时间序列 + 汇总。全链路统一命名 input_hit/input_miss/output
# （不含 cached/uncached）。命中率 = input_hit/(input_hit+input_miss)，分母 0 时前端
# 显示 "—"，故后端【不返回】hit_rate 字段，由前端按需计算。
# ---------------------------------------------------------------------------

UsageGranularity = Literal["day", "week", "month"]
UsageGroupBy = Literal["none", "model", "path"]
# 6 条真实 LLM 业务路径（gap_analysis/roadmap 是纯规则、无 LLM，不在此列）
UsagePath = Literal["chat", "resume", "jd", "optimize", "blindspot", "mastery"]


class UsageBucket(BaseModel):
    """时间序列单桶三类 token（不含 total/hit_rate）。"""

    bucket_start: str  # ISO 字符串（UTC，带 +00:00）
    input_hit: int
    input_miss: int
    output: int


class UsageSeries(BaseModel):
    """一条序列（group_by=none 时长度为 1：key='all'）。buckets 与全局桶轴逐桶对齐。"""

    key: str
    label: str
    provider: str = ""
    buckets: list[UsageBucket] = Field(default_factory=list)


class UsageTimeseriesOut(BaseModel):
    granularity: UsageGranularity
    group_by: UsageGroupBy
    bucket_starts: list[str] = Field(default_factory=list)  # 全局共享桶轴（ISO）
    series: list[UsageSeries] = Field(default_factory=list)


class UsageGroupStat(BaseModel):
    """汇总分组（by_model / by_path 同构复用，不含 hit_rate）。by_path 的 provider 为空。"""

    key: str
    label: str
    provider: str = ""
    input_hit: int
    input_miss: int
    output: int
    calls: int


class UsageSummaryOut(BaseModel):
    total_input_hit: int
    total_input_miss: int
    total_output: int
    total_calls: int
    by_model: list[UsageGroupStat] = Field(default_factory=list)
    by_path: list[UsageGroupStat] = Field(default_factory=list)
