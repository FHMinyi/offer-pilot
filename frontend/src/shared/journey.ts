// 旅程 / 任务相关的展示常量与本地日期工具（前端单一真源）。
// 阶段中文标签对齐后端 JourneyStage 枚举；本地自然日用于打卡 date 与「今日」过滤。

import type { JourneyStage, TaskKind } from '../types'

/** 五阶段展示标签（对齐后端 diagnosing/executing/applying/interviewing/closing）。 */
export const STAGE_LABEL: Record<JourneyStage, string> = {
  diagnosing: '诊断中',
  executing: '执行中',
  applying: '投递中',
  interviewing: '面试中',
  closing: '终局复盘',
}

/** 阶段顺序（步骤条高亮当前阶段用）。 */
export const STAGE_ORDER: JourneyStage[] = [
  'diagnosing',
  'executing',
  'applying',
  'interviewing',
  'closing',
]

/** 任务类别中文标签。 */
export const KIND_LABEL: Record<TaskKind, string> = {
  learn: '学习',
  deliverable: '产出',
  interview: '面试',
  review: '复盘',
}

/** 任务类别图标。 */
export const KIND_ICON: Record<TaskKind, string> = {
  learn: '📘',
  deliverable: '🔨',
  interview: '🎤',
  review: '🔁',
}

/**
 * 本地自然日 YYYY-MM-DD（用于打卡 date 与今日过滤）。
 * 用本地时区拼接，避免 toISOString() 的 UTC 跨日偏移。
 */
export function localTodayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
