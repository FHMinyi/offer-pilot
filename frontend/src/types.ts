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

/** 历史列表项（精简） */
export interface AnalysisSummary {
  id: number
  target_role: string
  match_score: number
  engine: string
  job_count: number
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

/** 技能本体图谱 */
export interface SkillGraph {
  proficiency_levels: string[]
  categories: { category: string; skills: { key: string; name: string }[] }[]
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
}

/** 对话上下文：随消息一并提交给后端的简历/JD/目标岗位等信息 */
export interface ChatContext {
  resume_text?: string // 已上传/粘贴的简历全文
  jd_texts?: string[] // 已添加的 JD 原文列表
  target_role?: string
  weeks?: number // 1~12，默认 4
  analysis_run_id?: number | null // 最近一次匹配分析 id，用于第二步生成学习计划跨轮定位
}

/** 工具调用活动：用于在对话界面展示 Agent 的工具调用过程 */
export interface ToolActivity {
  id: string
  name: string
  label: string
  ok?: boolean // 工具是否成功返回；未返回时为 undefined（进行中）
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
  | { role: 'user'; text: string }
  | { role: 'assistant'; blocks: PersistedBlock[]; noThinking?: boolean; error?: string }

/**
 * 会话持久化上下文：随会话一并存盘的简历/JD/目标岗位等信息，
 * 用于「历史续聊」时恢复上下文，让用户在原有基础上继续对话。
 * 字段与运行期 ChatContext 对齐（resume_text/jd_texts/target_role/weeks/analysis_run_id）。
 */
export interface ChatPersistContext {
  resume_text?: string // 已上传/粘贴的简历全文
  jd_texts?: string[] // 已添加的 JD 原文列表
  target_role?: string
  weeks?: number // 1~12，默认 4
  analysis_run_id?: number | null // 最近一次匹配分析 id
}

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
