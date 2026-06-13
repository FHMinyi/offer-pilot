// OfferPilot 前端共享类型定义
// 严格对应后端契约，所有视图与组件统一从此处导入。

/** 技能引用：用于 JD 的 must_have / nice_to_have 列表 */
export interface SkillRef {
  key: string
  name: string
  category: string
}

/** 技能缺口项：缺失或薄弱的技能 */
export interface GapItem {
  key: string
  name: string
  category: string
  required_by: string[] // 来自哪些 JD（岗位标题），即来源说明
  frequency: number // 多少个 JD 要求该技能
  priority: '高' | '中' | '低'
  gap_level: '缺失' | '薄弱'
  reason: string // 为什么判为缺失/薄弱
}

/** 已具备技能项 */
export interface PossessedItem {
  key: string
  name: string
  category: string
  evidence: string[] // 简历中支持该技能的证据词
  required_by: string[] // 哪些 JD 要求（可能为空）
}

/** 单个岗位画像 */
export interface PerJob {
  title: string
  company: string
  responsibilities: string[]
  requirements: string[]
  must_have: SkillRef[]
  nice_to_have: SkillRef[]
}

/** 综合岗位画像（多个 JD 聚合） */
export interface JobProfile {
  titles: string[]
  responsibilities: string[]
  requirements: string[]
  tech_stack: string[]
  jobs: PerJob[]
}

/** 技能缺口分析结果 */
export interface SkillGap {
  must_have_gaps: GapItem[]
  nice_to_have_gaps: GapItem[]
  possessed: PossessedItem[]
}

/** 简历优化建议 */
export interface ResumeSuggestion {
  title: string
  detail: string
  related_skills: string[]
}

/** 学习路线中的单周计划 */
export interface WeekItem {
  week: number
  focus_skills: string[]
  tasks: string[]
  deliverables: string[]
  estimated_hours: number
  interview_focus: string[]
}

/** 一次分析的完整结果 */
export interface AnalysisResult {
  match_score: number // 0-100
  summary: string
  engine: string // 'rule' | 'llm:openai' | 'llm:anthropic'
  target_role: string
  job_profile: JobProfile
  skill_gap: SkillGap
  resume_suggestions: ResumeSuggestion[]
  roadmap: WeekItem[]
}

/** 一次分析记录（持久化后返回） */
export interface AnalysisRun {
  id: number
  resume_id: number
  job_ids: number[]
  target_role: string
  weeks: number
  match_score: number
  engine: string
  result: AnalysisResult
  created_at: string
}

/** 已保存的 JD（测试 JD 库的一条记录，可复用到多次分析） */
export interface SavedJd {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
}

/** 简历解析/上传返回 */
export interface ResumeOut {
  id: number
  raw_text: string
  structured: Record<string, unknown>
  source_type: string
  created_at: string
}

/** 流式对话中的单条消息（assistant 为之前的回复文本） */
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  time?: string // 该消息发生时刻（本地字符串）；后端拼成【时间】前缀注入正文
}

/**
 * 前端自定义大语言模型覆盖（BYO LLM）：按会话覆盖服务端 .env 的 provider/端点/模型。
 * 六字段均为 string，留空＝回退服务端配置；api_key 仅存浏览器 localStorage、随请求发给本地后端、不入库。
 */
export interface LLMOverride {
  provider: string // openai / anthropic / ''(=用服务端)
  base_url: string // 自定义端点，留空＝官方/服务端
  api_key: string // API Key，仅存本地浏览器
  model: string // 默认档（对话/优化/面经/费曼/出题/判定 6 处）
  model_resume: string // 简历解析档（选填，空＝回退默认/服务端）
  model_jd: string // JD 解析档（选填，空＝回退默认/服务端）
}

/** 对话上下文：随消息一并提交给后端的简历/JD/目标岗位等信息 */
export interface ChatContext {
  resume_text?: string // 已上传/粘贴的简历全文
  jd_texts?: string[] // 已添加的 JD 原文列表
  target_role?: string
  weeks?: number // 1~12，默认 4
  analysis_run_id?: number | null // 最近一次匹配分析 id，用于第二步生成学习计划跨轮定位
  tone?: number // E3 语气强度 0=最温柔…100=最严格（默认 50）
  persona?: string // E3 人设键（B5 预留三人设，默认 'default'）
}

/** 单条联网搜索结果（web_search 工具产出，供前端折叠展示） */
export interface SearchResultItem {
  title: string
  url: string
  snippet: string // 网页摘要（后端已截断）
}

/** 模型“思考强度”档位：off 关闭思考，low/medium/high/xhigh/max 逐级加强 */
export type ReasoningEffort = 'off' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

// ===================================================================
//  会话持久化
//  说明：把对话界面渲染用的消息（ChatView 的 AssistantBlock / turn）
//  序列化为「可持久化子集」存盘——去掉 streaming / collapsed / reasoningOpen
//  等纯瞬态字段，仅保留可重建对话视图所需的数据。
// ===================================================================

/**
 * 持久化后的「助手回合 block」。
 * 字段与 ChatView 中的 AssistantBlock 严格一致（reasoning / text / tool / report），
 * 以便存盘与回放时无损还原同一套有序 blocks 渲染模型。
 */
export type PersistedBlock =
  // 普通回复（markdown）
  | { kind: 'text'; text: string }
  // 思考过程（markdown）
  | { kind: 'reasoning'; text: string }
  // 工具活动；ok 未定义=进行中，status 为最后一条子步骤文案，
  // steps 为累积的「分析过程日志」（每行一条，按到达顺序追加）；
  // query/results 仅 web_search 工具有：承载搜索关键词与结果列表，供折叠展示。
  | {
      kind: 'tool'
      id: string
      name: string
      label: string
      ok?: boolean
      status?: string
      steps?: string[]
      query?: string
      results?: SearchResultItem[]
    }
  // 结构化报告卡
  | { kind: 'report'; analysis_run_id: number; result: AnalysisResult }

/**
 * 持久化后的「单条消息」。
 * user 仅文本；assistant 为有序 blocks + 可选「无思考」标记与错误信息。
 */
export type PersistedTurn =
  | { role: 'user'; text: string; time?: string } // time=发送时刻
  | {
      role: 'assistant'
      blocks: PersistedBlock[]
      noThinking?: boolean
      error?: string
      usage?: TurnUsage // 本轮 token 用量（气泡小字 + 续聊重算会话累计）
      time?: string // 回复完成时刻
    }

/**
 * 会话持久化上下文：随会话一并存盘的简历/JD/目标岗位等信息，
 * 用于「历史续聊」时恢复上下文，让用户在原有基础上继续对话。
 * 字段与运行期 ChatContext 对齐（resume_text/jd_texts/target_role/weeks/analysis_run_id）。
 * 两者七字段逐一同构，故直接取别名；若日后持久化形态与运行期分叉，再拆回独立接口。
 */
export type ChatPersistContext = ChatContext

/** 会话列表项（精简，按更新时间倒序） */
export interface ConversationSummary {
  id: number
  title: string
  turn_count: number
  created_at: string
  updated_at: string
}

/** 单个会话的完整记录（含全部回合与续聊上下文） */
export interface ConversationDetail {
  id: number
  title: string
  turns: PersistedTurn[]
  context: ChatPersistContext // 续聊上下文（简历/JD/目标岗位/周数/分析 id）
  created_at: string
  updated_at: string
}

// ===================================================================
//  里程碑一 · 有状态闭环（任务 / 打卡 / 旅程 / 进度）
//  snake_case 严格对齐后端 schemas（TaskOut / CheckInOut / JourneyOut / ProgressOut）。
// ===================================================================

/** 任务四态：todo 待办 / doing 进行中 / done 已完成 / skipped 系统软删 */
export type TaskStatus = 'todo' | 'doing' | 'done' | 'skipped'
/** 任务类别：learn 学习 / deliverable 产出 / interview 面试 / review 复盘 */
export type TaskKind = 'learn' | 'deliverable' | 'interview' | 'review'

/** 掌握度第二层：unknown 未验证 / mastered 已掌握（荣誉态 ⭐，仅 learn 类有意义） */
export type TaskMastery = 'unknown' | 'mastered'

/** roadmap 物化出的可勾选任务行 */
export interface Task {
  id: number
  user_id: string
  journey_id: number | null
  analysis_run_id: number
  week: number
  order_index: number
  skill_key: string
  title: string
  kind: TaskKind
  weight: number
  status: TaskStatus
  done: boolean // 便利冗余字段 =(status==='done')，后端一并返回
  planned_date: string | null // YYYY-MM-DD
  done_at: string | null
  created_at: string
  // 双层状态第二层（仅 learn 类有意义）：mastery 字符串 + mastered 便利字段 =(mastery==='mastered')
  mastery: TaskMastery // 'unknown' | 'mastered'
  mastered: boolean
  mastered_at: string | null
}

/** PATCH /api/tasks/{id} 请求体 */
export interface TaskPatch {
  status?: TaskStatus
  weight?: number
  planned_date?: string | null
}

/** 每日打卡记录 */
export interface CheckIn {
  id: number
  date: string // YYYY-MM-DD（客户端本地自然日）
  mood: string
  note: string
  minutes: number
  completed_task_ids: number[] // 引用 Task.id
  created_at: string
  updated_at: string
}

/** POST /api/checkins 请求体（upsert，同 date 覆盖） */
export interface CheckInUpsert {
  date?: string // 缺省=服务器当日；前端通常传本地自然日
  mood?: string
  note?: string
  minutes?: number
  completed_task_ids?: number[]
}

/** 旅程五阶段展示标签：诊断/执行/投递/面试/终局 */
export type JourneyStage = 'diagnosing' | 'executing' | 'applying' | 'interviewing' | 'closing'

/** 旅程主表（单用户取最新 active 一条） */
export interface JourneyState {
  id: number
  target_role: string
  analysis_run_id: number | null
  stage: JourneyStage
  status: string // active/paused/succeeded/unmet/withdrawn
  start_date: string | null
  planned_weeks: number
  current_week: number
  signals: Record<string, unknown> // E1.2 再规划信号(progress_health/carried_over/remaining)
  last_replanned_at: string | null // 最近一次动态重排时间
  created_at: string
  updated_at: string
}

/** POST /api/journey/{id}/replan 请求体 */
export interface ReplanRequest {
  settle?: boolean // 结算降权（结算按钮传 true）
  today?: string // 本地自然日 YYYY-MM-DD
}

/** 动态再规划返回：更新后的旅程 + 全部活跃任务 */
export interface ReplanResult {
  journey: JourneyState
  tasks: Task[]
}

/** 单周进度（聚合 Task） */
export interface WeekProgress {
  week: number
  total: number
  done: number
}

/** 最近 N 天打卡热力的单元（E4 坚持天数可视化，旧→今） */
export interface RecentDay {
  date: string // YYYY-MM-DD
  checked: boolean
}

// ===================================================================
//  轨道 F1 · 面经复盘 → 盲区提取 → 权重回灌
// ===================================================================

/** 面试盲区：归一到技能本体的薄弱/被问倒技能（high/mid/low） */
export interface BlindSpot {
  skill_key: string
  skill_name: string
  severity: 'high' | 'mid' | 'low'
  evidence: string[] // 命中的原始词/被问到的点
  matched: boolean // 是否命中当前计划任务（命中=已被权重回灌）
}

/** 面经复盘记录 */
export interface InterviewLog {
  id: number
  company: string
  role: string
  content: string
  blind_spots: BlindSpot[]
  created_at: string
}

/** POST /api/interviews 请求体 */
export interface InterviewCreate {
  content: string
  company?: string
  role?: string
  today?: string // 本地自然日；回灌时把命中任务拉到这天（进入今日任务）
}

/** 提交面经回包：复盘记录 + 被回灌的任务 + 计划未覆盖的盲区（建议加练） */
export interface InterviewReplay {
  interview: InterviewLog
  boosted_tasks: Task[]
  unmatched_skills: BlindSpot[]
}

/** 进度汇总（GET /api/progress 实时聚合 + 惰性 streak） */
export interface ProgressSummary {
  total_tasks: number
  done_tasks: number
  completion_rate: number // 0~1
  current_week: number
  week_progress: WeekProgress[]
  current_streak: number
  longest_streak: number
  last_checkin_date: string | null
  checked_in_today: boolean
  recent_days: RecentDay[] // E4：最近 7 个自然日打卡热力（旧→今，末位为今天）
  // 掌握度叠加维度（与 completion_rate/done_tasks 语义独立，不相互覆盖）
  mastered_tasks: number // 已升级为 mastered ⭐ 的任务数
  total_learn_tasks: number // learn 类任务总数（mastery_rate 的分母）
  mastery_rate: number // 0~1，= mastered_tasks / total_learn_tasks
}

// ===================================================================
//  费曼/出题判定学习掌握度（把校验前移到学习环节 · 复用 F1 学习闭环引擎）
//  snake_case 严格对齐后端 schemas（MasteryCheckOut / MasteryJudgeOut / QuizGenerateOut）。
// ===================================================================

/** 判定模式：feynman 费曼复述 / quiz AI 出题 */
export type MasteryMode = 'feynman' | 'quiz'

/** 掌握度四档 + 空串（降级/自评时无 AI 评级，前端不显示评级徽章） */
export type MasteryVerdict = 'excellent' | 'good' | 'fair' | 'poor' | ''

/** 出题模式 AI 出的一道题（hint 为可选作答方向提示） */
export interface MasteryQuestion {
  q: string
  hint: string
}

/** 一条判定记录（可回看）。gaps 复用 F1 的 BlindSpot（后端为 BlindSpotItem，字段同构）。 */
export interface MasteryCheck {
  id: number
  task_id: number | null
  mode: MasteryMode
  verdict: MasteryVerdict
  passed: boolean
  feedback: string
  followup_questions: string[]
  gaps: BlindSpot[]
  engine: string
  created_at: string
}

/** 判定回包（仿 InterviewReplay）：判定记录 + 被判定任务 + 回灌任务 + 未覆盖缺口。 */
export interface MasteryJudgeOut {
  check: MasteryCheck
  task: Task // 被判定的任务（含更新后的 mastery）
  available: boolean // 是否走了真实 AI 判定（false=降级，引导手动标记）
  boosted_tasks: Task[]
  unmatched_skills: BlindSpot[]
}

/** 出题模式第一步：为某 learn 任务生成 2-3 道题。 */
export interface QuizGenerateOut {
  task_id: number
  questions: MasteryQuestion[]
  available: boolean // false=未配置 LLM，前端引导走「我已掌握」手动标记
}

// ===================================================================
//  token 用量统计子系统（snake_case 严格镜像后端，端到端唯一口径）
//  三类 token 全链路统一命名：input_hit / input_miss / output（绝不出现 cached/uncached）。
//  命中率 = input_hit/(input_hit+input_miss)，分母 0 时前端显示 "—"（后端不返回 hit_rate）。
// ===================================================================

/** 本轮对话 token 用量（SSE usage 事件载荷；total 由后端算好一并下发）。 */
export interface TurnUsage {
  input_hit: number // 命中缓存的输入 token
  input_miss: number // 未命中缓存的输入 token
  output: number // 输出 token
  total?: number // = input_hit + input_miss + output（SSE 带，历史回放可缺省）
}

/** 时间粒度三档：day 过去 24h 按本地整点小时 / week 过去 7 天 / month 过去 30 天。 */
export type UsageGranularity = 'day' | 'week' | 'month'

/** 聚合维度：none 总计 / model 按模型 / path 按功能。 */
export type UsageGroupBy = 'none' | 'model' | 'path'

/** 图表指标（纯前端切换，不上送后端）：tokens token 用量 / hitRate 缓存命中率%。 */
export type UsageMetric = 'tokens' | 'hitRate'

/** 真实 LLM 业务路径（6 条；gap_analysis/roadmap 纯规则无 LLM，不在此列）。 */
export type UsagePath = 'chat' | 'resume' | 'jd' | 'optimize' | 'blindspot' | 'mastery'

/** 单个时间桶的三类 token 计数（不含 total/hit_rate）。 */
export interface UsageBucket {
  bucket_start: string // ISO 字符串，对齐全局共享桶轴
  input_hit: number
  input_miss: number
  output: number
}

/** 一条时序序列（group_by=none 时长度=1，key="all"/label="全部"）。 */
export interface UsageSeries {
  key: string
  label: string
  provider: string // by_path 时为空字符串
  buckets: UsageBucket[] // 与 bucket_starts 逐桶对齐、连续补零
}

/** 时序聚合返回：共享桶轴 + 多序列（每序列 buckets 与 bucket_starts 逐桶对齐）。 */
export interface UsageTimeseries {
  granularity: UsageGranularity
  group_by: UsageGroupBy
  bucket_starts: string[] // 全局共享桶轴（ISO）
  series: UsageSeries[]
}

/** 汇总分组统计行（by_model/by_path 同构复用；不含 hit_rate）。 */
export interface UsageGroupStat {
  key: string
  label: string
  provider: string // by_path 时为空字符串
  input_hit: number
  input_miss: number
  output: number
  calls: number // 调用次数
}

/** 用量汇总返回：总计 + 按模型/按功能分组（空库 → 全 0 + 空数组）。 */
export interface UsageSummary {
  total_input_hit: number
  total_input_miss: number
  total_output: number
  total_calls: number
  by_model: UsageGroupStat[] // 建议按 input_miss 降序（最该优化的浮顶）
  by_path: UsageGroupStat[] // provider 为空
}
