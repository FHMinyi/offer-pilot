// 一轮流式对话的 SSE 编排 + 停止（从 ChatView.vue 抽出）：
//   · runChat：重置助手消息可变状态 → streamChat 消费 SSE → 各 handler 仅更新
//     传入的助手消息响应式对象（与模板渲染解耦）；流式期间对单条 turn 的深层
//     变更（追加 block / 更新工具状态 / 思考块默认展开）唯一写者在此；
//   · 契约：runChat 返回的 Promise resolve 即一轮完整收尾——含中止路径
//     （streamChat 被 abort 时安静 return、不调 onDone），故收尾逻辑写在
//     await 之后而非 onDone 回调里；折叠思考块 / 自动保存 / 收尾贴底的串接
//     经 onTurnFinished 交由 ChatView 编排；
//   · streaming / statusLine 的单一来源在此；abortController 私有，stop() 中止当前轮。

import { ref, type Ref } from 'vue'
import { streamChat } from '../api/client'
import type { ChatContext, ChatMessage, ReasoningEffort, TurnUsage } from '../types'
import { clearAnalysisToolStatus, findPendingTool, findToolById, localStamp } from './chatModel'
import type { AssistantBlock, AssistantTurn } from './chatModel'
// 自定义大语言模型（BYO LLM）：六字段全空时 effectiveOverride() 为 undefined，回退后端 .env
import { effectiveOverride } from './llmConfig'

export interface ChatStreamDeps {
  /** 思考强度选择（发起每轮时取当前值，随 reasoning_effort 提交）。 */
  effort: Ref<ReasoningEffort>
  /** 当前 context 的纯净快照（含 analysis_run_id / tone），由调用方提供。 */
  buildContext: () => ChatContext
  /** report 事件到达：上报本次匹配分析 id（供第二步 generate_plan 跨轮使用）。 */
  onReportRunId: (id: number) => void
  /** usage 事件到达：上报本轮 token 用量（会话累计由调用方维护）。 */
  onUsage: (e: TurnUsage) => void
  /** 一轮完整收尾（正常 / 中止 / 出错均触发）：折叠 / 保存 / 贴底由 ChatView 串接。 */
  onTurnFinished: (a: AssistantTurn) => void
}

// 取末块。
function lastBlock(a: AssistantTurn): AssistantBlock | undefined {
  return a.blocks[a.blocks.length - 1]
}

export function useChatStream(deps: ChatStreamDeps) {
  // 高层阶段提示（onStatus 的兜底）——显示在输入区上方的细条。
  // 注意：分析类工具（analyze_match / generate_plan）运行期间的子步骤优先写入对应 tool 块的 status；
  // 仅在找不到进行中的工具块时，才退化为这里的顶部细条。
  const statusLine = ref('')

  // 流式进行中标记与中止控制器。
  const streaming = ref(false)
  let abortController: AbortController | null = null

  // 真正执行一轮 SSE：handlers 仅更新传入的助手消息对象，与渲染解耦。
  async function runChat(
    assistant: AssistantTurn,
    requestMessages: ChatMessage[],
  ): Promise<void> {
    // 重置该条消息的可变状态（用于重试场景复用同一对象）
    assistant.blocks = []
    assistant.error = undefined
    assistant.streaming = true
    assistant.reasoningOpen = {}
    assistant.noThinking = false
    // 记录发起本轮所用的思考强度（结束时据此判断「应有思考却无思考」；
    // 重试时会按当前选择刷新，符合「发起该轮时所用强度」语义）。
    const turnEffort = deps.effort.value
    assistant.effort = turnEffort

    streaming.value = true
    statusLine.value = ''
    abortController = new AbortController()

    await streamChat(
      {
        messages: requestMessages,
        context: deps.buildContext(),
        reasoning_effort: turnEffort,
        // 自定义大语言模型覆盖（六字段全空则为 undefined，回退后端 .env）。
        llm_override: effectiveOverride(),
        // 当前本地时间（可读字符串）——让 AI 知道“现在”，避免检索旧年份信息。
        client_time: new Date().toLocaleString('zh-CN', { hour12: false }),
      },
      {
        // 思考增量：末块是 reasoning 则追加，否则新开一个 reasoning 块（流式默认展开）
        onReasoning: (e) => {
          const last = lastBlock(assistant)
          if (last && last.kind === 'reasoning') {
            last.text += e.text
          } else {
            assistant.blocks.push({ kind: 'reasoning', text: e.text })
            assistant.reasoningOpen[assistant.blocks.length - 1] = true
          }
        },
        // 增量文本：末块是 text 则追加，否则新开一个 text 块
        onDelta: (e) => {
          const last = lastBlock(assistant)
          if (last && last.kind === 'text') {
            last.text += e.text
          } else {
            assistant.blocks.push({ kind: 'text', text: e.text })
          }
        },
        // 工具调用 → 追加一个「进行中」工具块（steps 初始化为空，承载过程日志）
        onToolCall: (e) => {
          assistant.blocks.push({
            kind: 'tool',
            id: e.id,
            name: e.name,
            label: e.label,
            steps: [],
            resultsOpen: false,
          })
        },
        // 阶段/子进度：把 message【追加】到「最近一个未完成的工具块」的 steps 过程日志，
        // 并把 status 记为最后一条（展示以 steps 列表为准）；
        // 找不到进行中的工具块才退化为顶部细条。
        onStatus: (e) => {
          const pending = findPendingTool(assistant)
          if (pending) {
            if (!pending.steps) pending.steps = []
            pending.steps.push(e.message)
            pending.status = e.message
            statusLine.value = ''
          } else {
            statusLine.value = e.message
          }
        },
        // 工具返回 → 按 id 更新对应块（标记完成 + 替换为结果摘要 + 清空进行中单行；
        // steps 过程日志保留，供用户回看分析过程）
        onToolResult: (e) => {
          const t = findToolById(assistant, e.id)
          if (t) {
            t.ok = e.ok
            if (e.label) t.label = e.label
            t.status = undefined
          } else {
            // 兜底：未见过 tool_call 也补一个已完成块，避免结果丢失
            assistant.blocks.push({
              kind: 'tool',
              id: e.id,
              name: e.name,
              label: e.label,
              ok: e.ok,
            })
          }
        },
        // 联网搜索结果详情 → 挂到对应 web_search 工具块（默认折叠，用户可展开查看）
        onSearchResults: (e) => {
          const t = findToolById(assistant, e.id)
          if (t) {
            t.query = e.query
            t.results = e.results
          }
        },
        // 结构化报告 → 追加报告块，并把对应分析类工具块的 status 清空
        onReport: (e) => {
          clearAnalysisToolStatus(assistant)
          // 上报最近一次匹配分析 id，供第二步 generate_plan 跨轮使用
          deps.onReportRunId(e.analysis_run_id)
          assistant.blocks.push({
            kind: 'report',
            analysis_run_id: e.analysis_run_id,
            result: e.result,
          })
        },
        // 本轮 token 用量 → 记到该条消息（气泡小字）并上报会话累计
        onUsage: (e) => {
          assistant.usage = e
          deps.onUsage(e)
        },
        // 出错 → 记录到该条消息，模板内展示错误条 + 重试
        onError: (e) => {
          assistant.error = e.message || '对话出错，请重试。'
        },
        // 本轮结束（仅正常完成走到；abort 静默 return、出错走 onError 不走这里）
        onDone: () => {
          statusLine.value = ''
          // 助手时间戳 = 全部回复完成那一刻（不含流式中途/工具调用）
          assistant.time = localStamp()
        },
      },
      abortController.signal,
    )

    // 流结束（正常 / 中止 / 出错）后统一收尾。
    // 必须放在 await 之后：streamChat 被中止时安静 return、不调 onDone，
    // 只有这里能保证三种路径（正常 / 中止 / 出错）都走到收尾。
    assistant.streaming = false
    streaming.value = false
    statusLine.value = ''
    abortController = null
    // 「无思考」提示：本轮发起时强度非 off，但模型未输出任何 reasoning 块，
    // 且本轮无错误（出错时不提示，避免干扰错误条）。
    assistant.noThinking =
      turnEffort !== 'off' &&
      !assistant.error &&
      !assistant.blocks.some((b) => b.kind === 'reasoning')
    // 兜底：若本轮既无任何内容、也无「无思考」提示（如 off 档且模型零输出），
    // 补一条占位文本，确保气泡仍可见、消息不至于凭空消失。
    if (!assistant.error && !assistant.noThinking && assistant.blocks.length === 0) {
      assistant.blocks.push({ kind: 'text', text: '（本轮无输出）' })
    }
    // 折叠思考块 / 自动保存 / 收尾贴底等串接交由 ChatView 编排
    deps.onTurnFinished(assistant)
  }

  // 流式中点击「停止」：中止当前请求（runChat 的 await 之后照常收尾）。
  function stop(): void {
    abortController?.abort()
  }

  return { streaming, statusLine, runChat, stop }
}
