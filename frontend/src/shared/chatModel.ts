// 对话回合视图模型（ChatTurn / AssistantBlock）+ 围绕它的全部纯函数。
// 从 ChatView.vue 抽出，供 ChatView（流式）与 ConversationView（回放）共用：
//   · 类型：助手回复的有序 blocks 模型与渲染用消息结构；
//   · 序列化：serializeTurns / deserializeTurns 是会话持久化的【事实 schema】
//     （后端零校验整存整取），逐字段白名单投影与条件写入语义不可随意改动；
//   · 纯函数：投影请求消息、派生标题、token 用量累计/缩写、报告定位、
//     工具块查找、折叠收尾等——全部显式传参，不读任何组件闭包状态。

import type {
  AnalysisResult,
  ChatContext,
  ChatMessage,
  PersistedBlock,
  PersistedTurn,
  ReasoningEffort,
  SearchResultItem,
  TurnUsage,
} from '../types'
import { isAnalysisTool } from './chatTools'

// ---------- 助手消息的有序 block 模型 ----------
// 一个助手回合由若干有序 block 组成，渲染严格按数组顺序输出。
export type AssistantBlock =
  // 思考过程（markdown，默认折叠）
  | { kind: 'reasoning'; text: string }
  // 普通回复（markdown）
  | { kind: 'text'; text: string }
  // 工具活动；status=最后一条子步骤文案（仅进行中时有意义）；
  // steps=累积的「分析过程日志」（每行一条，按到达顺序追加，完成后保留供回看）；
  // query/results 仅 web_search：搜索关键词与结果列表；resultsOpen=结果折叠态（瞬态，不持久化）
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
      resultsOpen?: boolean
    }
  // 结构化报告卡
  | { kind: 'report'; analysis_run_id: number; result: AnalysisResult }

// ---------- 渲染用消息结构 ----------
// 用户消息：仅文本。
export interface UserTurn {
  role: 'user'
  text: string
}
// 助手消息：有序 blocks + 可选错误 + 流式标记 + 折叠态。
export interface AssistantTurn {
  role: 'assistant'
  blocks: AssistantBlock[]
  error?: string
  streaming: boolean
  // 触发本轮的对话历史快照（供「重试」复用，不含本占位消息）。
  requestMessages?: ChatMessage[]
  // 各 reasoning 块的展开态，按块在 blocks 中的下标索引。
  // 流式期间默认展开、本轮结束后自动折叠；用户可手动点击切换。
  reasoningOpen: Record<number, boolean>
  // 发起本轮时所选的思考强度（用于结束时判断「应有思考却无思考」）。
  effort?: ReasoningEffort
  // 本轮结束后置位：发起时强度 !== 'off' 但模型未输出任何 reasoning 块。
  noThinking?: boolean
  // 本轮 token 用量（SSE usage 事件到达后置位）：气泡小字展示输入(命中)/输出。
  usage?: TurnUsage
}
export type ChatTurn = UserTurn | AssistantTurn

// ===================================================================
//  token 用量
// ===================================================================

// 把一轮 usage 累加进累计值（纯函数，便于 reduce 重算历史）。
export function addUsage(acc: TurnUsage, e: TurnUsage): TurnUsage {
  const input_hit = acc.input_hit + (e.input_hit || 0)
  const input_miss = acc.input_miss + (e.input_miss || 0)
  const output = acc.output + (e.output || 0)
  return { input_hit, input_miss, output, total: input_hit + input_miss + output }
}

// token 数 k 缩写：<1000 原样；≥1000 显示「x.xk」（去掉多余 0）。
export function fmtTokens(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  if (v < 1000) return String(v)
  const k = v / 1000
  return `${k >= 100 ? Math.round(k) : Number(k.toFixed(1))}k`
}

// ===================================================================
//  请求投影
// ===================================================================

// 把一条助手消息的所有 text 块拼接为发给后端的纯文本（忽略思考/工具/报告）。
function assistantPlainText(t: AssistantTurn): string {
  return t.blocks
    .filter((b): b is Extract<AssistantBlock, { kind: 'text' }> => b.kind === 'text')
    .map((b) => b.text)
    .join('')
}

// 把渲染用消息投影为发给后端的 { role, content }。
// user 取其文本；assistant 取所有 text 块拼接。
export function toPayloadMessages(list: ChatTurn[]): ChatMessage[] {
  return list.map((t) =>
    t.role === 'user'
      ? { role: 'user', content: t.text }
      : { role: 'assistant', content: assistantPlainText(t) },
  )
}

// 当前 context 的纯净快照（去掉空字段，避免回传无意义数据）。
// 同一份快照同时用于「随每条消息提交」与「随会话存盘」（ChatPersistContext
// 与 ChatContext 同构，故统一返回 ChatContext）。
// runId=最近一次匹配分析 id（无则 null，不写入）；tone=E3 语气强度，无条件随快照携带。
export function snapshotChatContext(
  context: ChatContext,
  runId: number | null,
  tone: number,
): ChatContext {
  const ctx: ChatContext = { weeks: context.weeks ?? 4 }
  if (context.resume_text && context.resume_text.trim()) {
    ctx.resume_text = context.resume_text
  }
  if (context.jd_texts && context.jd_texts.length) {
    ctx.jd_texts = [...context.jd_texts]
  }
  if (context.target_role && context.target_role.trim()) {
    ctx.target_role = context.target_role.trim()
  }
  if (runId != null) {
    ctx.analysis_run_id = runId
  }
  ctx.tone = tone // E3：语气强度随对话提交 / 随会话存盘
  return ctx
}

// ===================================================================
//  会话持久化（serializeTurns 的投影即事实存储 schema，改动须慎之又慎）
// ===================================================================

// 把渲染用 turns 序列化为可持久化子集（丢弃 streaming / reasoningOpen /
// requestMessages / effort 等瞬态字段；assistant 仅留 blocks/noThinking/error，
// user 仅留 text）。block 结构与 AssistantBlock / PersistedBlock 严格一致。
export function serializeTurns(list: ChatTurn[]): PersistedTurn[] {
  return list.map((t): PersistedTurn => {
    if (t.role === 'user') {
      return { role: 'user', text: t.text }
    }
    const blocks: PersistedBlock[] = t.blocks.map((b) => {
      switch (b.kind) {
        case 'text':
          return { kind: 'text', text: b.text }
        case 'reasoning':
          return { kind: 'reasoning', text: b.text }
        case 'tool':
          return {
            kind: 'tool',
            id: b.id,
            name: b.name,
            label: b.label,
            ok: b.ok,
            status: b.status,
            steps: b.steps,
            query: b.query,
            results: b.results,
          }
        case 'report':
          return {
            kind: 'report',
            analysis_run_id: b.analysis_run_id,
            result: b.result,
          }
      }
    })
    const turn: PersistedTurn = { role: 'assistant', blocks }
    if (t.noThinking) turn.noThinking = true
    if (t.error) turn.error = t.error
    if (t.usage) turn.usage = t.usage // 本轮 token 用量随会话存盘
    return turn
  })
}

// 把持久化的 PersistedTurn[] 反序列化为内部渲染用 ChatTurn[]。
// user → { role, text }；assistant → { role, blocks, noThinking, error, streaming:false, reasoningOpen:{} }。
// blocks 结构与 PersistedBlock / AssistantBlock 一致，逐块映射即可无损还原；
// 未知 kind（如旧版前端读到未来版本数据）整块跳过，不让会话回放崩掉。
export function deserializeTurns(list: PersistedTurn[]): ChatTurn[] {
  return list.map((t): ChatTurn => {
    if (t.role === 'user') {
      return { role: 'user', text: t.text }
    }
    const blocks: AssistantBlock[] = []
    for (const b of t.blocks) {
      switch (b.kind) {
        case 'text':
          blocks.push({ kind: 'text', text: b.text })
          break
        case 'reasoning':
          blocks.push({ kind: 'reasoning', text: b.text })
          break
        case 'tool':
          blocks.push({
            kind: 'tool',
            id: b.id,
            name: b.name,
            label: b.label,
            ok: b.ok,
            status: b.status,
            steps: b.steps,
            query: b.query,
            results: b.results,
            // 搜索结果折叠态为瞬态：还原时统一以收起态呈现（默认折叠）
            resultsOpen: false,
          })
          break
        case 'report':
          blocks.push({
            kind: 'report',
            analysis_run_id: b.analysis_run_id,
            result: b.result,
          })
          break
        default:
          // 未知 kind：跳过该块（向前兼容加固，崩 → 忽略）
          break
      }
    }
    return {
      role: 'assistant',
      blocks,
      error: t.error,
      streaming: false,
      // 历史回合不保留瞬态的展开态，统一以收起态还原（用户可手动展开回看）
      reasoningOpen: {},
      noThinking: t.noThinking,
      usage: t.usage, // 还原本轮 token 用量（气泡小字 + 会话累计重算）
    }
  })
}

// 取首条 user 文本截断到约 30 字作为标题；无则「未命名对话」。
export function deriveTitle(list: ChatTurn[]): string {
  const firstUser = list.find((t): t is UserTurn => t.role === 'user')
  const text = firstUser?.text.trim() ?? ''
  if (!text) return '未命名对话'
  return text.length > 30 ? `${text.slice(0, 30)}…` : text
}

// ===================================================================
//  报告 / 工具块定位
// ===================================================================

// 倒序遍历所有回合，取「最后一个」report 块；无则 null。
// 同时支持运行时 ChatTurn[] 与持久化 PersistedTurn[]（两者的 report 块同构）：
// 前者服务右侧报告面板（最新报告摘要），后者服务续聊恢复 currentRunId。
export function findLastReportBlock(
  list: readonly (ChatTurn | PersistedTurn)[],
): Extract<AssistantBlock, { kind: 'report' }> | null {
  for (let ti = list.length - 1; ti >= 0; ti--) {
    const t = list[ti]
    if (t.role !== 'assistant') continue
    for (let bi = t.blocks.length - 1; bi >= 0; bi--) {
      const b = t.blocks[bi]
      if (b.kind === 'report') return b
    }
  }
  return null
}

// 找「最近一个未完成（ok===undefined）的工具块」。
export function findPendingTool(
  a: AssistantTurn,
): Extract<AssistantBlock, { kind: 'tool' }> | undefined {
  for (let i = a.blocks.length - 1; i >= 0; i--) {
    const b = a.blocks[i]
    if (b.kind === 'tool' && b.ok === undefined) return b
  }
  return undefined
}

// 按 id 找工具块。
export function findToolById(
  a: AssistantTurn,
  id: string,
): Extract<AssistantBlock, { kind: 'tool' }> | undefined {
  for (const b of a.blocks) {
    if (b.kind === 'tool' && b.id === id) return b
  }
  return undefined
}

// 报告到达时，清空对应分析类工具块（analyze_match / generate_plan）仍残留的子步骤文案。
export function clearAnalysisToolStatus(a: AssistantTurn): void {
  for (let i = a.blocks.length - 1; i >= 0; i--) {
    const b = a.blocks[i]
    if (b.kind === 'tool' && isAnalysisTool(b.name)) {
      b.status = undefined
      return
    }
  }
}

// 本轮结束后折叠所有思考块。
export function collapseAllReasoning(a: AssistantTurn): void {
  a.blocks.forEach((b, idx) => {
    if (b.kind === 'reasoning') a.reasoningOpen[idx] = false
  })
}

// ===================================================================
//  渲染判定
// ===================================================================

// 是否需要渲染气泡容器：有任意 block（非报告）、流式中、出错、或有「无思考」提示。
// 报告块改在右侧面板展示（消息流里仅留引用 chip），故气泡是否出现只看
// 「非报告 block / 流式 / 错误 / 无思考提示」。
export function hasBubble(a: AssistantTurn): boolean {
  if (a.streaming || a.error || a.noThinking || a.usage) return true
  return a.blocks.some((b) => b.kind !== 'report')
}

// 校验搜索结果链接协议：仅放行 http/https，挡掉 javascript:/data: 等危险协议，
// 防止脏数据或中间人注入可执行链接（搜索结果来自外部 Tavily，需视为不可信）。
export function isSafeUrl(url: unknown): boolean {
  if (typeof url !== 'string' || !url) return false
  try {
    const p = new URL(url)
    return p.protocol === 'http:' || p.protocol === 'https:'
  } catch {
    return false
  }
}
