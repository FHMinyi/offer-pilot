// OfferPilot 对话流 SSE 解析（纯函数，便于单测）。
// 从 client.ts 的 streamChat 闭包中提出：分帧（processSseBuffer）与单帧分派
// （dispatchSseFrame）不依赖 fetch/reader/AbortSignal，仅依赖传入的 handlers。
// ChatStreamHandlers 在此定义，client.ts re-export 以保持调用方导入路径可用。

import type { AnalysisResult, SearchResultItem, TurnUsage } from '../types'

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
  /** 本轮 token 用量（input_hit/input_miss/output/total）：气泡小字 + 会话累计 */
  onUsage?: (e: TurnUsage) => void
  /** 出错 */
  onError?: (e: { message: string }) => void
  /** 本轮结束 */
  onDone?: () => void
}

/**
 * 解析单帧 SSE，提取 event 类型与 data 文本并分派到对应回调。
 * 兼容 \r\n 行尾；多行 data 按规范以 \n 拼接；空行与注释行（:开头）跳过；
 * data 非合法 JSON 时仅 error 事件以纯文本兜底，其余忽略；未知事件类型忽略（向前兼容）。
 */
export function dispatchSseFrame(frame: string, handlers: ChatStreamHandlers): void {
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
    case 'usage':
      handlers.onUsage?.(data as TurnUsage)
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

/**
 * 增量分帧器：把累积文本里以空行(\n\n)分隔的完整帧逐个回调，
 * 返回残余的不完整数据（跨 chunk 半帧），由调用方继续累积。
 * 全空白帧（如多余空行产生的）跳过不回调。
 */
export function processSseBuffer(buffer: string, onFrame: (frame: string) => void): string {
  let sep = buffer.indexOf('\n\n')
  while (sep !== -1) {
    const frame = buffer.slice(0, sep)
    buffer = buffer.slice(sep + 2)
    if (frame.trim()) onFrame(frame)
    sep = buffer.indexOf('\n\n')
  }
  return buffer
}
