// api/sse.ts 契约测试：dispatchSseFrame 的 10 类事件分派与容错行为、
// processSseBuffer 的增量分帧（跨 chunk 半帧 / 单 buffer 多帧）。
// 这是前后端 SSE 协议在前端的唯一落点，任何分派/分帧语义变化都应先在此处现形。

import { describe, expect, it, vi } from 'vitest'
import { dispatchSseFrame, processSseBuffer, type ChatStreamHandlers } from './sse'

// 构造一帧 SSE 文本（event 行 + 单行 data）。
function frameOf(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}`
}

// 全部 10 类回调都挂上 mock，便于断言「只分派目标事件、其余不动」。
function allHandlers() {
  return {
    onStatus: vi.fn(),
    onReasoning: vi.fn(),
    onDelta: vi.fn(),
    onToolCall: vi.fn(),
    onToolResult: vi.fn(),
    onSearchResults: vi.fn(),
    onReport: vi.fn(),
    onUsage: vi.fn(),
    onError: vi.fn(),
    onDone: vi.fn(),
  } satisfies ChatStreamHandlers
}

// 10 类事件 → 对应回调名 + 代表性 payload（done 无 payload 单独处理）。
const eventCases: {
  event: string
  handler: keyof ReturnType<typeof allHandlers>
  payload: unknown
}[] = [
  { event: 'status', handler: 'onStatus', payload: { phase: 'search', message: '正在联网检索…' } },
  { event: 'reasoning', handler: 'onReasoning', payload: { text: '先拆解 JD 要求' } },
  { event: 'delta', handler: 'onDelta', payload: { text: '你好，' } },
  {
    event: 'tool_call',
    handler: 'onToolCall',
    payload: { id: 't1', name: 'web_search', label: '联网搜索' },
  },
  {
    event: 'tool_result',
    handler: 'onToolResult',
    payload: { id: 't1', name: 'web_search', label: '找到 5 条结果', ok: true },
  },
  {
    event: 'search_results',
    handler: 'onSearchResults',
    payload: {
      id: 't1',
      query: 'golang 后端 面试',
      results: [{ title: '某文', url: 'https://example.com', snippet: '摘要' }],
    },
  },
  {
    event: 'report',
    handler: 'onReport',
    payload: { analysis_run_id: 7, result: { match_score: 80, summary: '匹配良好' } },
  },
  {
    event: 'usage',
    handler: 'onUsage',
    payload: { input_hit: 100, input_miss: 50, output: 30, total: 180 },
  },
  { event: 'error', handler: 'onError', payload: { message: '上游超时' } },
]

describe('dispatchSseFrame', () => {
  it.each(eventCases)('$event 事件分派到 $handler 且 payload 透传', ({ event, handler, payload }) => {
    const handlers = allHandlers()
    dispatchSseFrame(frameOf(event, payload), handlers)
    expect(handlers[handler]).toHaveBeenCalledTimes(1)
    expect(handlers[handler]).toHaveBeenCalledWith(payload)
    // 其余回调一律不被触碰
    for (const [name, fn] of Object.entries(handlers)) {
      if (name !== handler) expect(fn).not.toHaveBeenCalled()
    }
  })

  it('done 事件分派到 onDone（无参数）', () => {
    const handlers = allHandlers()
    dispatchSseFrame(frameOf('done', {}), handlers)
    expect(handlers.onDone).toHaveBeenCalledTimes(1)
    expect(handlers.onReasoning).not.toHaveBeenCalled()
  })

  it('多行 data 按 SSE 规范以 \\n 拼接（经 error 纯文本兜底直接观察拼接结果）', () => {
    const handlers = allHandlers()
    dispatchSseFrame('event: error\ndata: 第一行\ndata: 第二行', handlers)
    expect(handlers.onError).toHaveBeenCalledWith({ message: '第一行\n第二行' })
  })

  it('多行 data 拼接后整体 JSON.parse（合法 JSON 跨行下发）', () => {
    const handlers = allHandlers()
    dispatchSseFrame('event: delta\ndata: {"text":\ndata: "a"}', handlers)
    expect(handlers.onDelta).toHaveBeenCalledWith({ text: 'a' })
  })

  it('兼容 \\r\\n 行尾', () => {
    const handlers = allHandlers()
    dispatchSseFrame('event: delta\r\ndata: {"text":"hi"}\r', handlers)
    expect(handlers.onDelta).toHaveBeenCalledWith({ text: 'hi' })
  })

  it('纯注释行 / 无 data 行的帧不分派任何回调', () => {
    const handlers = allHandlers()
    dispatchSseFrame(': keep-alive 心跳注释', handlers)
    dispatchSseFrame('event: delta', handlers) // 只有 event 没有 data
    for (const fn of Object.values(handlers)) expect(fn).not.toHaveBeenCalled()
  })

  it('data 非合法 JSON：error 事件以纯文本兜底', () => {
    const handlers = allHandlers()
    dispatchSseFrame('event: error\ndata: 上游裸文本报错', handlers)
    expect(handlers.onError).toHaveBeenCalledWith({ message: '上游裸文本报错' })
  })

  it('data 非合法 JSON：非 error 事件静默忽略', () => {
    const handlers = allHandlers()
    dispatchSseFrame('event: delta\ndata: 不是 JSON', handlers)
    for (const fn of Object.values(handlers)) expect(fn).not.toHaveBeenCalled()
  })

  it('未知事件类型忽略（向前兼容）', () => {
    const handlers = allHandlers()
    dispatchSseFrame(frameOf('future_event', { foo: 1 }), handlers)
    for (const fn of Object.values(handlers)) expect(fn).not.toHaveBeenCalled()
  })
})

describe('processSseBuffer', () => {
  it('跨 chunk 半帧：完整帧回调、残余半帧返回，续传后补齐再回调', () => {
    const onFrame = vi.fn()
    // 第一段：一帧完整 + 半帧残余
    const rest1 = processSseBuffer(
      'event: delta\ndata: {"text":"a"}\n\nevent: delta\ndata: {"te',
      onFrame,
    )
    expect(onFrame).toHaveBeenCalledTimes(1)
    expect(onFrame).toHaveBeenCalledWith('event: delta\ndata: {"text":"a"}')
    expect(rest1).toBe('event: delta\ndata: {"te')
    // 第二段：残余 + 后续 chunk 拼接补齐
    const rest2 = processSseBuffer(`${rest1}xt":"b"}\n\n`, onFrame)
    expect(onFrame).toHaveBeenCalledTimes(2)
    expect(onFrame).toHaveBeenLastCalledWith('event: delta\ndata: {"text":"b"}')
    expect(rest2).toBe('')
  })

  it('单 buffer 多帧按顺序逐帧回调', () => {
    const frames: string[] = []
    const rest = processSseBuffer(
      'event: status\ndata: {"phase":"a","message":"一"}\n\n' +
        'event: delta\ndata: {"text":"二"}\n\n' +
        'event: done\ndata: {}\n\n',
      (f) => frames.push(f),
    )
    expect(frames).toEqual([
      'event: status\ndata: {"phase":"a","message":"一"}',
      'event: delta\ndata: {"text":"二"}',
      'event: done\ndata: {}',
    ])
    expect(rest).toBe('')
  })

  it('全空白帧（多余空行产生）跳过不回调', () => {
    const onFrame = vi.fn()
    const rest = processSseBuffer('\n\n  \n\nevent: done\ndata: {}\n\n', onFrame)
    expect(onFrame).toHaveBeenCalledTimes(1)
    expect(onFrame).toHaveBeenCalledWith('event: done\ndata: {}')
    expect(rest).toBe('')
  })
})
