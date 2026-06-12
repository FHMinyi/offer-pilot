// shared/chatModel.ts + shared/chatTools.ts 契约测试。
// serializeTurns 的投影即会话持久化的【事实 schema】（后端零校验整存整取），
// 此处把「白名单投影 / 瞬态剥除 / 缺字段兜底 / 未知 kind 跳过」全部钉死：
// 任何改坏存量会话回放的序列化改动都应先在此现形。

import { describe, expect, it } from 'vitest'
import type { AnalysisResult, PersistedBlock, PersistedTurn, TurnUsage } from '../types'
import {
  addUsage,
  deriveTitle,
  deserializeTurns,
  findLastReportBlock,
  fmtTokens,
  serializeTurns,
  snapshotChatContext,
  type AssistantTurn,
  type ChatTurn,
} from './chatModel'
import {
  TOOL_ANALYZE_MATCH,
  TOOL_GENERATE_PLAN,
  TOOL_WEB_SEARCH,
  isAnalysisTool,
  toolIcon,
} from './chatTools'

// 序列化对 report.result 整体透传、不关心内部结构，用最小桩即可。
function stubResult(score: number, summary: string): AnalysisResult {
  return { match_score: score, summary } as AnalysisResult
}

// 断言并收窄为助手回合。
function asAssistant(t: ChatTurn): AssistantTurn {
  if (t.role !== 'assistant') throw new Error('期望助手回合')
  return t
}

describe('serializeTurns / deserializeTurns 往返', () => {
  // 一条带满所有字段（含全部瞬态）的运行时对话。
  function fullRuntimeTurns(): ChatTurn[] {
    return [
      { role: 'user', text: '帮我分析这份简历' },
      {
        role: 'assistant',
        blocks: [
          { kind: 'reasoning', text: '先拆 JD 的硬性要求' },
          { kind: 'text', text: '好的，开始分析。' },
          {
            kind: 'tool',
            id: 't1',
            name: TOOL_WEB_SEARCH,
            label: '联网搜索',
            ok: true,
            status: '已完成',
            steps: ['检索岗位要求', '汇总结果'],
            query: 'golang 后端 招聘要求',
            results: [{ title: '某文', url: 'https://example.com', snippet: '摘要' }],
            resultsOpen: true, // 瞬态：不应入库
          },
          { kind: 'report', analysis_run_id: 3, result: stubResult(80, '匹配良好') },
        ],
        error: '网络中断',
        streaming: true, // 瞬态
        requestMessages: [{ role: 'user', content: '帮我分析这份简历' }], // 瞬态
        reasoningOpen: { 0: true }, // 瞬态
        effort: 'high', // 瞬态
        noThinking: true,
        usage: { input_hit: 100, input_miss: 50, output: 30, total: 180 },
      },
    ]
  }

  it('瞬态字段（streaming/requestMessages/reasoningOpen/effort/resultsOpen）不入序列化结果', () => {
    const json = JSON.stringify(serializeTurns(fullRuntimeTurns()))
    for (const key of ['streaming', 'requestMessages', 'reasoningOpen', 'effort', 'resultsOpen']) {
      expect(json).not.toContain(`"${key}"`)
    }
  })

  it('user 文本与四种 block + error/noThinking/usage 经存盘 JSON 往返无损', () => {
    const turns = fullRuntimeTurns()
    // 经 JSON 往返模拟「后端整存整取」（undefined 值键在此消失）
    const stored = JSON.parse(JSON.stringify(serializeTurns(turns))) as PersistedTurn[]
    const restored = deserializeTurns(stored)

    expect(restored[0]).toEqual({ role: 'user', text: '帮我分析这份简历' })
    const a = asAssistant(restored[1])
    expect(a.blocks).toEqual([
      { kind: 'reasoning', text: '先拆 JD 的硬性要求' },
      { kind: 'text', text: '好的，开始分析。' },
      {
        kind: 'tool',
        id: 't1',
        name: TOOL_WEB_SEARCH,
        label: '联网搜索',
        ok: true,
        status: '已完成',
        steps: ['检索岗位要求', '汇总结果'],
        query: 'golang 后端 招聘要求',
        results: [{ title: '某文', url: 'https://example.com', snippet: '摘要' }],
        resultsOpen: false, // 瞬态折叠态统一以收起态还原
      },
      { kind: 'report', analysis_run_id: 3, result: stubResult(80, '匹配良好') },
    ])
    expect(a.error).toBe('网络中断')
    expect(a.noThinking).toBe(true)
    expect(a.usage).toEqual({ input_hit: 100, input_miss: 50, output: 30, total: 180 })
    // 瞬态字段以默认形态重建
    expect(a.streaming).toBe(false)
    expect(a.reasoningOpen).toEqual({})
  })

  it('tool 块 ok===undefined（中断未返回）往返后仍为 undefined，且存盘 JSON 不含 ok 键', () => {
    const turns: ChatTurn[] = [
      {
        role: 'assistant',
        blocks: [{ kind: 'tool', id: 't1', name: TOOL_ANALYZE_MATCH, label: '分析中' }],
        streaming: false,
        reasoningOpen: {},
      },
    ]
    const storedJson = JSON.stringify(serializeTurns(turns))
    expect(storedJson).not.toContain('"ok"')
    const b = asAssistant(deserializeTurns(JSON.parse(storedJson) as PersistedTurn[])[0]).blocks[0]
    if (b.kind !== 'tool') throw new Error('期望 tool 块')
    expect(b.ok).toBeUndefined()
  })

  it('最小 tool 块（存量老数据，仅 id/name/label）反序列化不崩、缺省字段不臆造', () => {
    const stored: PersistedTurn[] = [
      {
        role: 'assistant',
        blocks: [{ kind: 'tool', id: 't9', name: TOOL_WEB_SEARCH, label: '联网搜索' }],
      },
    ]
    const b = asAssistant(deserializeTurns(stored)[0]).blocks[0]
    if (b.kind !== 'tool') throw new Error('期望 tool 块')
    expect(b.id).toBe('t9')
    expect(b.label).toBe('联网搜索')
    expect(b.ok).toBeUndefined()
    expect(b.status).toBeUndefined()
    expect(b.steps).toBeUndefined()
    expect(b.query).toBeUndefined()
    expect(b.results).toBeUndefined()
    expect(b.resultsOpen).toBe(false)
  })

  it('未知 kind 整块跳过（向前兼容），相邻块不受影响', () => {
    const stored: PersistedTurn[] = [
      {
        role: 'assistant',
        blocks: [
          { kind: 'text', text: '前' },
          { kind: 'hologram', payload: 1 } as unknown as PersistedBlock,
          { kind: 'text', text: '后' },
        ],
      },
    ]
    const a = asAssistant(deserializeTurns(stored)[0])
    expect(a.blocks).toEqual([
      { kind: 'text', text: '前' },
      { kind: 'text', text: '后' },
    ])
  })
})

describe('findLastReportBlock', () => {
  const turns: ChatTurn[] = [
    { role: 'user', text: '分析匹配度' },
    {
      role: 'assistant',
      blocks: [{ kind: 'report', analysis_run_id: 1, result: stubResult(60, '一') }],
      streaming: false,
      reasoningOpen: {},
    },
    { role: 'user', text: '出学习计划' },
    {
      role: 'assistant',
      blocks: [
        { kind: 'report', analysis_run_id: 2, result: stubResult(70, '二') },
        { kind: 'text', text: '计划如下' },
        { kind: 'report', analysis_run_id: 3, result: stubResult(80, '三') },
      ],
      streaming: false,
      reasoningOpen: {},
    },
  ]

  it('跨多轮倒序取「最后一个」report 块（同轮多报告也取最后）', () => {
    expect(findLastReportBlock(turns)?.analysis_run_id).toBe(3)
    // PersistedTurn[] 同样支持（续聊恢复 currentRunId 路径）
    expect(findLastReportBlock(serializeTurns(turns))?.analysis_run_id).toBe(3)
  })

  it('无报告返回 null', () => {
    expect(findLastReportBlock([])).toBeNull()
    const noReport: PersistedTurn[] = [
      { role: 'user', text: 'hi' },
      { role: 'assistant', blocks: [{ kind: 'text', text: '你好' }] },
    ]
    expect(findLastReportBlock(noReport)).toBeNull()
  })
})

describe('snapshotChatContext', () => {
  it('空字段剥除：空白 resume_text/target_role、空 jd_texts、null runId 均不写入；weeks 缺省 4', () => {
    const snap = snapshotChatContext(
      { resume_text: '   ', jd_texts: [], target_role: '  ', persona: 'default' },
      null,
      50,
    )
    expect(snap).toEqual({ weeks: 4, tone: 50 })
    // 键集严格如此（persona 不随快照携带；tone 无条件写入）
    expect(Object.keys(snap).sort()).toEqual(['tone', 'weeks'])
  })

  it('非空字段保留：target_role 去首尾空白、jd_texts 拷贝为新数组、runId 写入 analysis_run_id', () => {
    const jdTexts = ['JD 原文一']
    const snap = snapshotChatContext(
      { resume_text: '简历全文', jd_texts: jdTexts, target_role: ' 后端工程师 ', weeks: 8 },
      12,
      80,
    )
    expect(snap).toEqual({
      weeks: 8,
      resume_text: '简历全文',
      jd_texts: ['JD 原文一'],
      target_role: '后端工程师',
      analysis_run_id: 12,
      tone: 80,
    })
    expect(snap.jd_texts).not.toBe(jdTexts) // 防御性拷贝，不共享引用
  })
})

describe('token 用量', () => {
  it('addUsage 逐字段累加且 total 重算（不信任传入 total，缺省 total 也可累计）', () => {
    const zero: TurnUsage = { input_hit: 0, input_miss: 0, output: 0, total: 0 }
    const a = addUsage(zero, { input_hit: 100, input_miss: 50, output: 30, total: 999 })
    expect(a).toEqual({ input_hit: 100, input_miss: 50, output: 30, total: 180 })
    const b = addUsage(a, { input_hit: 1, input_miss: 2, output: 3 }) // 历史回放可缺省 total
    expect(b).toEqual({ input_hit: 101, input_miss: 52, output: 33, total: 186 })
  })

  it('fmtTokens 阈值：<1000 原样、≥1000 一位小数去零、≥100k 取整、非有限值按 0', () => {
    expect(fmtTokens(0)).toBe('0')
    expect(fmtTokens(999)).toBe('999')
    expect(fmtTokens(1000)).toBe('1k')
    expect(fmtTokens(1234)).toBe('1.2k')
    expect(fmtTokens(99949)).toBe('99.9k')
    expect(fmtTokens(100000)).toBe('100k')
    expect(fmtTokens(123456)).toBe('123k')
    expect(fmtTokens(NaN)).toBe('0')
  })
})

describe('deriveTitle', () => {
  it('取首条 user 文本（trim 后），空则「未命名对话」', () => {
    expect(deriveTitle([])).toBe('未命名对话')
    expect(deriveTitle([{ role: 'user', text: '   ' }])).toBe('未命名对话')
    expect(deriveTitle([{ role: 'user', text: '  帮我看看简历  ' }])).toBe('帮我看看简历')
  })

  it('超过 30 字截断并加省略号，恰好 30 字不截', () => {
    const exact30 = '字'.repeat(30)
    expect(deriveTitle([{ role: 'user', text: exact30 }])).toBe(exact30)
    expect(deriveTitle([{ role: 'user', text: '字'.repeat(31) }])).toBe(`${exact30}…`)
  })
})

describe('chatTools 工具名协议（后端实名：web_search / analyze_match / generate_plan）', () => {
  it('isAnalysisTool 仅认两个会产出 report 事件的分析类工具', () => {
    expect(isAnalysisTool(TOOL_ANALYZE_MATCH)).toBe(true)
    expect(isAnalysisTool(TOOL_GENERATE_PLAN)).toBe(true)
    expect(isAnalysisTool(TOOL_WEB_SEARCH)).toBe(false)
  })

  it('toolIcon：搜索🔍、分析📊、未知名默认🛠', () => {
    expect(toolIcon(TOOL_WEB_SEARCH)).toBe('🔍')
    expect(toolIcon(TOOL_ANALYZE_MATCH)).toBe('📊')
    expect(toolIcon(TOOL_GENERATE_PLAN)).toBe('📊')
    expect(toolIcon('unknown_tool')).toBe('🛠')
  })
})
