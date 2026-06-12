// 会话自动保存 / 续聊加载 / 新会话重置（从 ChatView.vue 抽出）：
//   · conversationId：当前会话在后端的 id（null=尚未保存）；每轮结束 persist
//     自动 upsert，并用返回 id 回填，实现「后续轮次更新同一会话」；
//   · sessionUsage：本会话 token 用量累计（流式 usage 事件经 addTurnUsage 累加；
//     续聊加载时从各轮 usage 重算，保持全链路统一口径）；
//   · 竞态防护（generation/epoch）：persist 在 await saveConversation 期间，
//     若会话身份已切换（reset/load 使 generation 递增），则不回填返回的 id——
//     防「保存返回覆盖新对话 id → 下一轮 upsert 把旧会话内容写进别的会话」。
// turns 所有权：本文件仅做【整体替换】（load 还原/失败清空）与序列化读取（persist）；
// 追加/截断等编辑由 ChatView 编排层负责。路由跳转 / flash 提示 / 滚动聚焦等视图
// 职责经 onLoaded / onLoadError 回调留在 ChatView。

import { computed, ref, type Ref } from 'vue'
import { getConversation, saveConversation } from '../api/client'
import type { ChatContext, TurnUsage } from '../types'
import {
  addUsage,
  deriveTitle,
  deserializeTurns,
  findLastReportBlock,
  serializeTurns,
} from './chatModel'
import type { ChatTurn } from './chatModel'
import { notifyConversationsChanged } from './appState'

export interface ConversationPersistenceDeps {
  /** 对话消息列表（reactive 数组）：仅整体替换（load）与序列化读取（persist）。 */
  turns: ChatTurn[]
  /** 续聊上下文（reactive）：load 时逐字段还原简历 / JD / 目标岗位 / 周数。 */
  context: ChatContext
  /** E3 语气强度：load 时恢复该会话存盘值（无则保持当前/默认）。 */
  tone: Ref<number>
  /** 最近一次匹配分析 id：load 时恢复 / 失败时清空（写者仍是 ChatView/流式层）。 */
  currentRunId: Ref<number | null>
  /** 当前 context 的存盘快照（与随消息提交的快照同构），由调用方提供。 */
  buildContext: () => ChatContext
  /** 载入成功收尾（滚到底部 / 聚焦输入框等视图职责留在 ChatView）。 */
  onLoaded: () => void
  /** 载入失败收尾（flash 提示与路由清理留在 ChatView）。 */
  onLoadError: (err: unknown) => void
}

// 会话累计的零值（新会话 / 加载失败回退用）。
function zeroUsage(): TurnUsage {
  return { input_hit: 0, input_miss: 0, output: 0, total: 0 }
}

export function useConversationPersistence(deps: ConversationPersistenceDeps) {
  // 当前会话在后端的 id：null 表示尚未保存（新会话）。
  const conversationId = ref<number | null>(null)

  // 正在加载历史会话的标记：避免加载期间触发自动保存等副作用。
  const loadingConversation = ref(false)

  // 本会话 token 用量累计（input_hit/input_miss/output/total）。
  const sessionUsage = ref<TurnUsage>(zeroUsage())

  // 本会话累计是否有数据（决定是否展示累计小字）。
  const hasSessionUsage = computed(() => (sessionUsage.value.total ?? 0) > 0)

  // 会话身份代数：reset / load 切换会话身份时递增；
  // 在途 persist 返回后据此判断是否还允许回填 conversationId（竞态防护）。
  let generation = 0

  // 每轮 SSE usage 事件累加到本会话累计。
  function addTurnUsage(e: TurnUsage): void {
    sessionUsage.value = addUsage(sessionUsage.value, e)
  }

  // upsert 当前会话：需至少 1 条 user 消息；用返回 id 回填 conversationId。
  // 失败仅 console 警告，不打扰用户。
  async function persist(): Promise<void> {
    // 历史会话加载中：跳过保存，避免与加载中的中间态竞争写回
    if (loadingConversation.value) return
    if (!deps.turns.some((t) => t.role === 'user')) return
    const gen = generation
    try {
      const saved = await saveConversation({
        id: conversationId.value,
        title: deriveTitle(deps.turns),
        turns: serializeTurns(deps.turns),
        // 随会话存盘当前上下文快照，供「历史续聊」恢复简历/JD/目标岗位/周数/分析 id
        context: deps.buildContext(),
      })
      // 竞态防护：await 期间若已切换会话身份（新对话 / 载入他会话），
      // 不回填本次返回的 id，防止后续轮次 upsert 覆盖别的会话。
      if (gen === generation) conversationId.value = saved.id
      // 通知左侧栏刷新「最近会话」列表（新会话/新标题即时出现）
      notifyConversationsChanged()
    } catch (err) {
      console.warn('[会话自动保存失败]', err)
    }
  }

  // 加载某段已存会话用于「续聊」：拉取详情 → 反序列化 turns → 恢复 context 与
  // conversationId / currentRunId → 经 onLoaded 收尾。失败经 onLoadError 收尾并
  // 回退为一段空白新对话。加载期间置位 loadingConversation，避免清空动作把会话
  // 洗成空白后被误保存。
  async function load(id: number): Promise<void> {
    if (!Number.isFinite(id) || id <= 0) return
    loadingConversation.value = true
    // 切换会话身份：作废在途 persist 的 id 回填
    generation += 1
    try {
      const detail = await getConversation(id)
      // 还原对话消息
      const restored = deserializeTurns(detail.turns)
      deps.turns.splice(0, deps.turns.length, ...restored)
      // 从各轮 usage 重算本会话 token 累计（续聊恢复全链路口径）
      sessionUsage.value = restored.reduce<TurnUsage>(
        (acc, t) => (t.role === 'assistant' && t.usage ? addUsage(acc, t.usage) : acc),
        zeroUsage(),
      )
      // 还原续聊上下文（简历 / JD / 目标岗位 / 周数）
      const ctx = detail.context ?? {}
      deps.context.resume_text =
        ctx.resume_text && ctx.resume_text.trim() ? ctx.resume_text : undefined
      deps.context.jd_texts = Array.isArray(ctx.jd_texts) ? [...ctx.jd_texts] : []
      deps.context.target_role = ctx.target_role ?? ''
      deps.context.weeks = ctx.weeks ?? 4
      // E3：恢复该会话存盘的语气强度（无则保持当前/默认）
      if (typeof ctx.tone === 'number' && ctx.tone >= 0 && ctx.tone <= 100) {
        deps.tone.value = ctx.tone
      }
      // 绑定到同一会话，后续轮次保存回此 id
      conversationId.value = detail.id
      // 恢复最近一次匹配分析 id：优先取 turns 中最后一个 report 块，
      // 兜底回退到持久化 context.analysis_run_id（两者通常一致）。
      deps.currentRunId.value =
        findLastReportBlock(detail.turns)?.analysis_run_id ?? ctx.analysis_run_id ?? null
      deps.onLoaded()
    } catch (err) {
      // 加载失败：回退为一段空白新对话；提示与路由清理经 onLoadError 留在 ChatView
      deps.turns.splice(0, deps.turns.length)
      conversationId.value = null
      deps.currentRunId.value = null
      sessionUsage.value = zeroUsage()
      deps.onLoadError(err)
    } finally {
      loadingConversation.value = false
    }
  }

  // 重置为全新会话身份：conversationId 置空（下次保存即新建）、累计清零、
  // generation 递增以作废在途 persist 的 id 回填。turns 清空由 ChatView 编排层负责。
  function reset(): void {
    generation += 1
    conversationId.value = null
    sessionUsage.value = zeroUsage()
  }

  return {
    conversationId,
    loadingConversation,
    sessionUsage,
    hasSessionUsage,
    addTurnUsage,
    persist,
    load,
    reset,
  }
}
