// OfferPilot 前端 API 客户端
// 统一使用相对路径 fetch('/api/...')，开发期由 Vite 代理转发到后端。
// 约定：非 2xx 响应一律 throw Error，错误信息优先取后端返回的 detail 字段。

import type {
  AnalysisRun,
  AnalysisResult,
  AnalysisSummary,
  ChatContext,
  ChatMessage,
  ChatPersistContext,
  CheckIn,
  CheckInUpsert,
  ConversationDetail,
  ConversationSummary,
  InterviewCreate,
  InterviewLog,
  InterviewReplay,
  JourneyPatch,
  JourneyState,
  PersistedTurn,
  ProgressSummary,
  ReasoningEffort,
  ReplanRequest,
  ReplanResult,
  ResumeOut,
  SavedJd,
  SearchResultItem,
  SkillGraph,
  Task,
  TaskPatch,
} from '../types'
import { deviceHeaders } from '../shared/device'
import { localTodayIso } from '../shared/journey'

/** 分析请求体（内联模式或引用模式均可） */
export interface RunAnalysisPayload {
  resume_text?: string
  jd_texts?: string[]
  resume_id?: number
  job_ids?: number[]
  target_role?: string
  weeks?: number
  prefer_structured?: boolean
}

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

/**
 * 发起一次分析。
 * 内联模式传 { resume_text, jd_texts, target_role, weeks }；
 * 引用模式传 { resume_id, job_ids, ... }。
 */
export async function runAnalysis(payload: RunAnalysisPayload): Promise<AnalysisRun> {
  const res = await apiFetch('/api/analysis/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<AnalysisRun>(res)
}

/** 获取历史分析列表（按时间倒序） */
export async function listAnalyses(): Promise<AnalysisSummary[]> {
  const res = await apiFetch('/api/analysis')
  return handle<AnalysisSummary[]>(res)
}

/** 获取单次分析的完整记录 */
export async function getAnalysis(id: number): Promise<AnalysisRun> {
  const res = await apiFetch(`/api/analysis/${id}`)
  return handle<AnalysisRun>(res)
}

/** 获取技能本体图谱 */
export async function getSkillGraph(): Promise<SkillGraph> {
  const res = await apiFetch('/api/skills/graph')
  return handle<SkillGraph>(res)
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
 * 流式对话事件回调集合。
 * 与后端 SSE 事件类型一一对应；除 onError/onDone 外均可选。
 */
export interface ChatStreamHandlers {
  /** 高层阶段提示（如“正在联网检索岗位技能…”）；run_analysis 运行期间也会多次到达，用于子进度 */
  onStatus?: (e: { phase: string; message: string }) => void
  /** 模型“思考过程”增量文本（流式，建议折叠展示并以 markdown 渲染） */
  onReasoning?: (e: { text: string }) => void
  /** 助手回复增量文本（拼接显示） */
  onDelta?: (e: { text: string }) => void
  /** Agent 调用工具 */
  onToolCall?: (e: { id: string; name: string; label: string }) => void
  /** 工具返回（label 为简短结果摘要） */
  onToolResult?: (e: { id: string; name: string; label: string; ok: boolean }) => void
  /** 联网搜索结果详情（id 关联对应 web_search 工具块；前端折叠展示） */
  onSearchResults?: (e: { id: string; query: string; results: SearchResultItem[] }) => void
  /** 结构化分析报告（渲染为报告卡） */
  onReport?: (e: { analysis_run_id: number; result: AnalysisResult }) => void
  /** 出错 */
  onError?: (e: { message: string }) => void
  /** 本轮结束 */
  onDone?: () => void
}

/**
 * 发起一次流式对话，消费后端 SSE（text/event-stream）。
 *
 * 读取 response.body 的 ReadableStream，用 TextDecoder 累积文本，按空行(\n\n)
 * 分帧；逐帧解析 `event:` 与 `data:` 行，对 data 做 JSON.parse，按事件类型分派到
 * 对应回调。流正常结束调用 onDone；若响应非 2xx 或读取/解析异常，调用 onError
 * （错误信息尽量取后端返回）。被 AbortSignal 中止时安静结束（不报错）。
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
  },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  // 判断异常是否由主动中止引发
  const isAborted = (err: unknown): boolean =>
    signal?.aborted === true ||
    (err instanceof DOMException && err.name === 'AbortError') ||
    (err instanceof Error && err.name === 'AbortError')

  // 解析单帧 SSE，提取 event 类型与 data 文本并分派
  const dispatchFrame = (frame: string): void => {
    let event = 'message' // SSE 默认事件名
    const dataLines: string[] = []
    for (const rawLine of frame.split('\n')) {
      const line = rawLine.replace(/\r$/, '') // 兼容 \r\n
      if (!line || line.startsWith(':')) continue // 空行或注释行
      if (line.startsWith('event:')) {
        event = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        // 去掉冒号后的单个前导空格（SSE 规范）
        dataLines.push(line.slice('data:'.length).replace(/^ /, ''))
      }
    }
    if (dataLines.length === 0) return
    const dataText = dataLines.join('\n')

    let data: unknown
    try {
      data = JSON.parse(dataText)
    } catch {
      // data 不是合法 JSON：仅 error 事件尝试以纯文本兜底，其余忽略
      if (event === 'error') {
        handlers.onError?.({ message: dataText || '对话流解析失败' })
      }
      return
    }

    switch (event) {
      case 'status':
        handlers.onStatus?.(data as { phase: string; message: string })
        break
      case 'reasoning':
        handlers.onReasoning?.(data as { text: string })
        break
      case 'delta':
        handlers.onDelta?.(data as { text: string })
        break
      case 'tool_call':
        handlers.onToolCall?.(data as { id: string; name: string; label: string })
        break
      case 'tool_result':
        handlers.onToolResult?.(
          data as { id: string; name: string; label: string; ok: boolean },
        )
        break
      case 'search_results':
        handlers.onSearchResults?.(
          data as { id: string; query: string; results: SearchResultItem[] },
        )
        break
      case 'report':
        handlers.onReport?.(
          data as { analysis_run_id: number; result: AnalysisResult },
        )
        break
      case 'error':
        handlers.onError?.(data as { message: string })
        break
      case 'done':
        handlers.onDone?.()
        break
      default:
        // 未知事件类型：忽略，保持向前兼容
        break
    }
  }

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
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        const frame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        if (frame.trim()) dispatchFrame(frame)
        sep = buffer.indexOf('\n\n')
      }
    }

    // 冲刷解码器并处理可能残留的最后一帧（无尾随空行的情况）
    buffer += decoder.decode()
    if (buffer.trim()) dispatchFrame(buffer)
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

/** 更新旅程（推进 stage / 改 target_role / 周数）。 */
export async function patchJourney(id: number, patch: JourneyPatch): Promise<JourneyState> {
  const res = await apiFetch(`/api/journey/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
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

/** 面经复盘列表（按时间倒序）。 */
export async function listInterviews(): Promise<InterviewLog[]> {
  const res = await apiFetch('/api/interviews')
  return handle<InterviewLog[]>(res)
}

/** 进度汇总（实时聚合 Task + 惰性 streak）。 */
export async function getProgress(journeyId?: number): Promise<ProgressSummary> {
  // 传客户端本地自然日，让 streak/checked_in_today/recent_days/current_week 以浏览器「今天」为锚点，
  // 与打卡 date（本地日）口径一致，避免服务器时区≠用户时区时跨日错位（见 progress.py 注释）。
  const res = await apiFetch(`/api/progress${qs({ journey_id: journeyId, today: localTodayIso() })}`)
  return handle<ProgressSummary>(res)
}
