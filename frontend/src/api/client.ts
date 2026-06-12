// OfferPilot 前端 API 客户端
// 统一使用相对路径 fetch('/api/...')，开发期由 Vite 代理转发到后端。
// 约定：非 2xx 响应一律 throw Error，错误信息优先取后端返回的 detail 字段。

import type {
  AnalysisRun,
  ChatContext,
  ChatMessage,
  ChatPersistContext,
  CheckIn,
  CheckInUpsert,
  ConversationDetail,
  ConversationSummary,
  InterviewCreate,
  InterviewReplay,
  JourneyState,
  LLMOverride,
  MasteryJudgeOut,
  MasteryQuestion,
  PersistedTurn,
  ProgressSummary,
  QuizGenerateOut,
  ReasoningEffort,
  ReplanRequest,
  ReplanResult,
  ResumeOut,
  SavedJd,
  Task,
  TaskPatch,
  UsageGranularity,
  UsageGroupBy,
  UsageSummary,
  UsageTimeseries,
} from '../types'
import { deviceHeaders } from '../shared/device'
import { localTodayIso } from '../shared/journey'
import { dispatchSseFrame, processSseBuffer, type ChatStreamHandlers } from './sse'

// SSE 回调类型定义已移至 sse.ts，此处 re-export 保持调用方导入路径不变
export type { ChatStreamHandlers } from './sse'

/**
 * 统一 fetch 包装：把设备归属头（X-Device-Id）合并进所有 /api 请求。
 * 不覆盖调用方已设的同名头；不注入 Content-Type（保 FormData 由浏览器自带边界）。
 * 所有 /api 调用（含 streamChat 的 SSE、uploadResume 的 FormData）一律走它。
 */
function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {})
  for (const [k, v] of Object.entries(deviceHeaders())) {
    if (!headers.has(k)) headers.set(k, v)
  }
  return fetch(input, { ...init, headers })
}

/** 把可选查询参数对象拼成 `?a=1&b=2`（忽略 undefined/null/空串）。 */
function qs(params: Record<string, string | number | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

/**
 * 从响应中解析后端错误信息。
 * 优先读取 JSON 中的 detail 字段；detail 可能是字符串或 FastAPI 校验错误数组。
 */
async function extractError(res: Response): Promise<string> {
  // 默认兜底信息
  let message = `请求失败（${res.status}）`
  try {
    const data = await res.clone().json()
    const detail = (data as { detail?: unknown })?.detail
    if (typeof detail === 'string' && detail.trim()) {
      message = detail
    } else if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI 校验错误：[{ loc, msg, type }, ...]
      message = detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg)
          }
          return String(item)
        })
        .join('；')
    } else if (typeof data === 'string' && data.trim()) {
      message = data
    }
  } catch {
    // 响应体不是 JSON，尝试读取纯文本
    try {
      const text = await res.clone().text()
      if (text.trim()) message = text
    } catch {
      // 忽略，保留兜底信息
    }
  }
  return message
}

/** 统一处理响应：非 2xx 抛错，2xx 解析 JSON */
async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(await extractError(res))
  }
  return (await res.json()) as T
}

/**
 * 上传简历 PDF，后端抽取文本并结构化。
 * @param file PDF 文件
 * @returns 解析后的简历对象（前端通常读取 raw_text 回填输入框）
 */
export async function uploadResume(file: File): Promise<ResumeOut> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetch('/api/resumes/upload', {
    method: 'POST',
    body: form,
  })
  return handle<ResumeOut>(res)
}

/** 获取单次分析的完整记录 */
export async function getAnalysis(id: number): Promise<AnalysisRun> {
  const res = await apiFetch(`/api/analysis/${id}`)
  return handle<AnalysisRun>(res)
}

/**
 * 用前端填写的自定义大模型配置从所填端点拉取可用模型列表（兼连通性测试）。
 * Key 以 POST body 上送本地后端（不落入 URL/日志）；后端约定不抛 5xx，
 * 失败时返回 { ok:false, error, models:[] } 让 UI 优雅退回手输。
 * 任何网络/解析异常本函数兜底为 { ok:false, models:[], error }。
 */
export async function fetchLLMModels(
  cfg: LLMOverride,
): Promise<{ ok: boolean; models: string[]; error?: string }> {
  try {
    const res = await apiFetch('/api/llm/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    })
    if (!res.ok) {
      return { ok: false, models: [], error: await extractError(res) }
    }
    const data = (await res.json()) as { ok?: unknown; models?: unknown; error?: unknown }
    return {
      ok: !!data.ok,
      models: Array.isArray(data.models) ? (data.models as string[]) : [],
      error: data.error as string | undefined,
    }
  } catch (e) {
    return { ok: false, models: [], error: String(e) }
  }
}

// ===================================================================
//  测试 JD 库（可保存/编辑/删除的 JD，复用到多次分析）
// ===================================================================

/** 获取已保存的 JD 列表（按 updated_at 倒序） */
export async function listSavedJds(): Promise<SavedJd[]> {
  const res = await apiFetch('/api/saved-jds')
  return handle<SavedJd[]>(res)
}

/** 新建一条已保存 JD */
export async function createSavedJd(p: { title: string; content: string }): Promise<SavedJd> {
  const res = await apiFetch('/api/saved-jds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
  return handle<SavedJd>(res)
}

/** 更新指定 id 的已保存 JD */
export async function updateSavedJd(
  id: number,
  p: { title: string; content: string },
): Promise<SavedJd> {
  const res = await apiFetch(`/api/saved-jds/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
  return handle<SavedJd>(res)
}

/** 删除指定 id 的已保存 JD */
export async function deleteSavedJd(id: number): Promise<{ ok: boolean }> {
  const res = await apiFetch(`/api/saved-jds/${id}`, { method: 'DELETE' })
  return handle<{ ok: boolean }>(res)
}

// ===================================================================
//  会话持久化
// ===================================================================

/**
 * 保存（新建或更新）一个会话。
 * id 为空/缺省=新建；非空=更新该 id 的会话。
 * context 为可选的续聊上下文（简历/JD/目标岗位/周数/分析 id），随 body 一并提交，
 * 供「历史续聊」恢复对话上下文。
 * @returns 会话元信息（id/title/created_at/updated_at）
 */
export async function saveConversation(payload: {
  id?: number | null
  title?: string
  turns: PersistedTurn[]
  context?: ChatPersistContext
}): Promise<{ id: number; title: string; created_at: string; updated_at: string }> {
  const res = await apiFetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<{ id: number; title: string; created_at: string; updated_at: string }>(res)
}

/** 获取会话列表（按更新时间倒序） */
export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await apiFetch('/api/conversations')
  return handle<ConversationSummary[]>(res)
}

/** 获取单个会话的完整记录（含全部回合） */
export async function getConversation(id: number): Promise<ConversationDetail> {
  const res = await apiFetch(`/api/conversations/${id}`)
  return handle<ConversationDetail>(res)
}

/**
 * 发起一次流式对话，消费后端 SSE（text/event-stream）。
 *
 * 读取 response.body 的 ReadableStream，用 TextDecoder 累积文本，分帧与单帧
 * 分派交给 sse.ts 的 processSseBuffer / dispatchSseFrame 纯函数。流正常结束调用
 * onDone；若响应非 2xx 或读取/解析异常，调用 onError（错误信息尽量取后端返回）。
 * 被 AbortSignal 中止时安静结束（不报错）。
 *
 * @param payload 对话历史与上下文
 * @param handlers 各类 SSE 事件的回调
 * @param signal 可选的中止信号（用于取消请求）
 */
export async function streamChat(
  payload: {
    messages: ChatMessage[]
    context: ChatContext
    /** 模型思考强度；默认 'medium'。'off' 表示关闭思考 */
    reasoning_effort?: ReasoningEffort
    /** 本地可读时间字符串，用于让 AI 知道“现在”，避免检索旧年份信息 */
    client_time?: string
    /** 按会话覆盖的自定义大模型配置（六字段全空时由调用方传 undefined） */
    llm_override?: LLMOverride
  },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  // 判断异常是否由主动中止引发
  const isAborted = (err: unknown): boolean =>
    signal?.aborted === true ||
    (err instanceof DOMException && err.name === 'AbortError') ||
    (err instanceof Error && err.name === 'AbortError')

  try {
    const res = await apiFetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })

    if (!res.ok) {
      handlers.onError?.({ message: await extractError(res) })
      return
    }
    if (!res.body) {
      handlers.onError?.({ message: '对话流不可用（响应无 body）' })
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    // 持续读取并按空行分帧
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // 以空行分隔的完整帧逐个取出；保留最后一段不完整数据于 buffer
      buffer = processSseBuffer(buffer, (frame) => dispatchSseFrame(frame, handlers))
    }

    // 冲刷解码器并处理可能残留的最后一帧（无尾随空行的情况）
    buffer += decoder.decode()
    if (buffer.trim()) dispatchSseFrame(buffer, handlers)
  } catch (err) {
    if (isAborted(err)) return // 主动中止：安静结束
    const message = err instanceof Error ? err.message : '对话流连接失败'
    handlers.onError?.({ message })
  }
}

// ===================================================================
//  里程碑一 · 有状态闭环（任务 / 打卡 / 旅程 / 进度）
// ===================================================================

/** 任务列表（按 week, order_index 升序）；可按 run / journey / week 过滤。 */
export async function listTasks(params: {
  analysis_run_id?: number
  journey_id?: number
  week?: number
} = {}): Promise<Task[]> {
  const res = await apiFetch(`/api/tasks${qs(params)}`)
  return handle<Task[]>(res)
}

/** 更新单个任务（status=done 写完成时间；可改 weight/planned_date）。 */
export async function patchTask(id: number, patch: TaskPatch): Promise<Task> {
  const res = await apiFetch(`/api/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return handle<Task>(res)
}

/** 打卡列表（按 date 倒序）；可选 start/end 闭区间过滤（YYYY-MM-DD）。 */
export async function listCheckIns(range: { start?: string; end?: string } = {}): Promise<CheckIn[]> {
  const res = await apiFetch(`/api/checkins${qs(range)}`)
  return handle<CheckIn[]>(res)
}

/** 当日打卡 upsert（同 date 覆盖）。 */
export async function upsertCheckIn(payload: CheckInUpsert): Promise<CheckIn> {
  const res = await apiFetch('/api/checkins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<CheckIn>(res)
}

/** 取最新 active 旅程；无（404）则返回 null（空态由调用方引导）。 */
export async function getJourney(): Promise<JourneyState | null> {
  const res = await apiFetch('/api/journey')
  if (res.status === 404) return null
  return handle<JourneyState>(res)
}

/** 动态再规划：按完成情况顺延/重组剩余日程（settle=true 时结算降权）。 */
export async function replanJourney(id: number, payload: ReplanRequest = {}): Promise<ReplanResult> {
  const res = await apiFetch(`/api/journey/${id}/replan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<ReplanResult>(res)
}

/** 提交一次面经复盘：抽盲区 + 权重回灌（命中任务提权并拉到今天）。 */
export async function createInterview(payload: InterviewCreate): Promise<InterviewReplay> {
  const res = await apiFetch('/api/interviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // 默认带本地自然日，让回灌把命中任务拉到「今天」；调用方显式传入可覆盖
    body: JSON.stringify({ today: localTodayIso(), ...payload }),
  })
  return handle<InterviewReplay>(res)
}

/** 进度汇总（实时聚合 Task + 惰性 streak）。 */
export async function getProgress(journeyId?: number): Promise<ProgressSummary> {
  // 传客户端本地自然日，让 streak/checked_in_today/recent_days/current_week 以浏览器「今天」为锚点，
  // 与打卡 date（本地日）口径一致，避免服务器时区≠用户时区时跨日错位（见 progress.py 注释）。
  const res = await apiFetch(`/api/progress${qs({ journey_id: journeyId, today: localTodayIso() })}`)
  return handle<ProgressSummary>(res)
}

// ===================================================================
//  费曼/出题判定学习掌握度（把校验前移到学习环节 · 复用 F1 学习闭环引擎）
//  仅 learn 类任务有此能力；判定一次性返回（非流式）。
// ===================================================================

/** 费曼模式判定：用户用自己的话复述某 learn 任务的原理/关键点，提交一次性判定。 */
export async function judgeFeynman(
  taskId: number,
  content: string,
  today?: string,
  reasoningEffort?: ReasoningEffort,
): Promise<MasteryJudgeOut> {
  const res = await apiFetch('/api/mastery/feynman', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // 默认带本地自然日，命中缺口回灌时把任务拉到「今天」（同 F1 口径）；调用方可覆盖
    body: JSON.stringify({
      task_id: taskId,
      content,
      today: today ?? localTodayIso(),
      ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
    }),
  })
  return handle<MasteryJudgeOut>(res)
}

/** 出题模式第一步：为某 learn 任务生成 2-3 道题（available=false 时引导手动标记）。 */
export async function generateQuiz(
  taskId: number,
  reasoningEffort?: ReasoningEffort,
): Promise<QuizGenerateOut> {
  const res = await apiFetch('/api/mastery/quiz/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task_id: taskId,
      ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
    }),
  })
  return handle<QuizGenerateOut>(res)
}

/** 出题模式第二步：提交答案判分（questions 由前端原样回传，后端无状态）。 */
export async function judgeQuiz(
  taskId: number,
  questions: MasteryQuestion[],
  answers: string[],
  today?: string,
  reasoningEffort?: ReasoningEffort,
): Promise<MasteryJudgeOut> {
  const res = await apiFetch('/api/mastery/quiz/judge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task_id: taskId,
      questions,
      answers,
      today: today ?? localTodayIso(),
      ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
    }),
  })
  return handle<MasteryJudgeOut>(res)
}

/** 「我已掌握 ⭐」：用户最终决定权，直接把任务标为 mastered（不依赖 LLM）。 */
export async function masterTask(taskId: number, today?: string): Promise<Task> {
  const res = await apiFetch(`/api/mastery/tasks/${taskId}/master`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ today: today ?? localTodayIso() }),
  })
  return handle<Task>(res)
}

// ===================================================================
//  token 用量统计子系统
//  两端点都按设备过滤（X-Device-Id 由 apiFetch 自动带）；空库永远 200。
// ===================================================================

/** 用量筛选条件（三端点共用；空值由 qs() 自动丢弃）。 */
export interface UsageFilters {
  group_by?: UsageGroupBy
  path?: string
  model?: string
  provider?: string
}

/**
 * 拉取用量时序聚合。
 * 自动带 tz_offset = 本地时区偏移分钟数取负（getTimezoneOffset() 的相反数；东八区得 +480），
 * 让后端按浏览器本地时间落桶（本地整点小时 / 本地自然日）。
 */
export async function fetchUsageTimeseries(
  granularity: UsageGranularity = 'day',
  q: UsageFilters = {},
): Promise<UsageTimeseries> {
  const tzOffset = -new Date().getTimezoneOffset()
  const res = await apiFetch(
    `/api/usage/timeseries${qs({
      granularity,
      tz_offset: tzOffset,
      group_by: q.group_by,
      path: q.path,
      model: q.model,
      provider: q.provider,
    })}`,
  )
  return handle<UsageTimeseries>(res)
}

/** 拉取用量汇总（总计 + 按模型/按功能分组）。 */
export async function fetchUsageSummary(q: UsageFilters = {}): Promise<UsageSummary> {
  const res = await apiFetch(
    `/api/usage/summary${qs({ path: q.path, model: q.model, provider: q.provider })}`,
  )
  return handle<UsageSummary>(res)
}
