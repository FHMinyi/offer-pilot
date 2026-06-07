<script setup lang="ts">
// 进度看板（里程碑一正反馈可视化 · E4 润色）：
//   完成率环 + 关键数值（数字滚动）+ 最近 7 天打卡热力 + E1 节奏洞察
//   + 五阶段步骤条（连线/✓/高亮）+ 周进度条（本周高亮/满格 ✓）。
// 按 B7「相对进度/完成度」：只展示进步类数字，不报 Offer 概率。
import { computed } from 'vue'
import type { JourneyState, ProgressSummary } from '../types'
import ScoreRing from './ui/ScoreRing.vue'
import { STAGE_LABEL, STAGE_ORDER, localTodayIso } from '../shared/journey'
import { useCountUp } from '../shared/useCountUp'

const props = defineProps<{
  progress: ProgressSummary
  journey?: JourneyState | null
}>()

const ratePct = computed(() => Math.round((props.progress.completion_rate || 0) * 100))
const currentStageIndex = computed(() => {
  const s = props.journey?.stage
  return s ? STAGE_ORDER.indexOf(s) : -1
})

// 数字滚动：进入看板时从 0 缓动到实际值（尊重 prefers-reduced-motion）。
const doneCount = useCountUp(() => props.progress.done_tasks)
const streakCount = useCountUp(() => props.progress.current_streak)
const longestCount = useCountUp(() => props.progress.longest_streak)
// 掌握度叠加维度（兜底防后端字段未上线时 undefined）
const masteredCount = useCountUp(() => props.progress.mastered_tasks ?? 0)

// 最近 7 天打卡热力（旧→今，后端 recent_days 保证 7 个单元、末位为今天）。
const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']
const todayIso = localTodayIso()
const recentDays = computed(() =>
  (props.progress.recent_days || []).map((d) => {
    const dt = new Date(`${d.date}T00:00:00`) // 本地零点解析，取本地星期/日
    return {
      date: d.date,
      checked: d.checked,
      dayNum: dt.getDate(),
      weekday: WEEKDAY[dt.getDay()] ?? '',
      isToday: d.date === todayIso,
    }
  }),
)

// E1 动态再规划信号 → 节奏洞察（严守 B7：只报相对进度/剩余条数，不报 Offer 概率）。
// 剩余条数用「实时聚合」(total-done) 而非 signals 旧快照——勾选任务后即时同步；
// carried_over 是「上次结算」的快照，文案如实标注「上次结算」，不冒充当前值。
const insight = computed(() => {
  const p = props.progress
  const total = p.total_tasks
  const remaining = Math.max(0, total - p.done_tasks)
  // 全部完成：无论是否重排过都给正反馈
  if (total > 0 && remaining === 0)
    return { tone: 'done' as const, text: '全部任务已完成，节奏拉满 🎉' }
  // 顺延/节奏类洞察依赖再规划信号，仅在发生过结算重排后展示
  const j = props.journey
  if (!j || !j.last_replanned_at) return null
  const carried = Number(((j.signals || {}) as { carried_over?: number }).carried_over ?? 0)
  if (carried > 0)
    return {
      tone: 'warn' as const,
      text: `上次结算顺延了 ${carried} 条逾期任务，已自动重排；当前剩余 ${remaining} 条。`,
    }
  return {
    tone: 'ok' as const,
    text: `节奏稳健，无逾期顺延；当前剩余 ${remaining} 条任务按计划推进。`,
  }
})

const insightIcon = (tone: 'ok' | 'warn' | 'done'): string =>
  tone === 'warn' ? '⚠' : tone === 'done' ? '🎉' : '✅'
</script>

<template>
  <div class="board stack">
    <div class="board__hero board__anim">
      <ScoreRing :score="ratePct" :size="120" caption="完成率" />
      <div class="board__stats">
        <div class="stat">
          <span class="stat__num">{{ doneCount }}/{{ progress.total_tasks }}</span>
          <span class="stat__label">已完成任务</span>
        </div>
        <div class="stat">
          <span class="stat__num">第 {{ progress.current_week }} 周</span>
          <span class="stat__label">当前进度</span>
        </div>
        <div class="stat">
          <span class="stat__num">🔥 {{ streakCount }}</span>
          <span class="stat__label">连续打卡（天）</span>
        </div>
        <div class="stat">
          <span class="stat__num">{{ longestCount }}</span>
          <span class="stat__label">最长连续（天）</span>
        </div>
        <div class="stat">
          <span class="stat__num">⭐ {{ masteredCount }}</span>
          <span class="stat__label">已掌握</span>
        </div>
      </div>
    </div>

    <!-- E1 节奏洞察：把动态再规划的结果带进看板（仅在重排发生后显示） -->
    <p v-if="insight" class="insight board__anim" :class="`insight--${insight.tone}`">
      <span class="insight__icon" aria-hidden="true">{{ insightIcon(insight.tone) }}</span>
      <span>{{ insight.text }}</span>
    </p>

    <!-- 最近 7 天打卡热力 -->
    <div v-if="recentDays.length" class="streak board__anim">
      <p class="streak__title">最近 7 天</p>
      <div class="streak__row" role="img" aria-label="最近 7 天打卡情况">
        <div
          v-for="d in recentDays"
          :key="d.date"
          class="streak__cell"
          :class="{ 'streak__cell--checked': d.checked, 'streak__cell--today': d.isToday }"
          :title="`${d.date}${d.checked ? '：已打卡' : '：未打卡'}`"
        >
          <span class="streak__num">{{ d.dayNum }}</span>
          <span class="streak__wd">{{ d.weekday }}</span>
        </div>
      </div>
    </div>

    <!-- 五阶段步骤条（连线 + 已过 ✓ + 当前高亮脉冲） -->
    <div v-if="journey" class="stages board__anim" aria-label="旅程阶段">
      <div
        v-for="(st, i) in STAGE_ORDER"
        :key="st"
        class="stages__item"
        :class="{
          'stages__item--active': i === currentStageIndex,
          'stages__item--past': i < currentStageIndex,
          'stages__item--filled': i <= currentStageIndex,
        }"
      >
        <span class="stages__dot" aria-hidden="true">
          <span v-if="i < currentStageIndex" class="stages__check">✓</span>
        </span>
        <span class="stages__label">{{ STAGE_LABEL[st] }}</span>
      </div>
    </div>

    <!-- 周进度条（本周高亮 + 满格标 ✓；条形=本周完成度，工作量见右侧 done/total 计数） -->
    <div v-if="progress.week_progress.length" class="weeks board__anim">
      <p class="weeks__title">各周完成度</p>
      <div
        v-for="w in progress.week_progress"
        :key="w.week"
        class="weekbar"
        :class="{
          'weekbar--current': w.week === progress.current_week,
          'weekbar--complete': w.total > 0 && w.done >= w.total,
        }"
      >
        <span class="weekbar__name">
          第 {{ w.week }} 周
          <span v-if="w.week === progress.current_week" class="weekbar__now">本周</span>
        </span>
        <div class="weekbar__track">
          <div
            class="weekbar__fill"
            :style="{ width: `${(w.done / Math.max(1, w.total)) * 100}%` }"
          />
        </div>
        <span class="weekbar__count">
          <span v-if="w.total > 0 && w.done >= w.total" class="weekbar__tick" aria-hidden="true">✓</span>
          {{ w.done }}/{{ w.total }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.board {
  gap: var(--space-5);
}

/* 进入时的轻量淡入上浮（reduced-motion 下禁用，见文末） */
.board__anim {
  animation: boardFadeUp 0.5s ease both;
}
.board__anim:nth-child(2) {
  animation-delay: 0.05s;
}
.board__anim:nth-child(3) {
  animation-delay: 0.1s;
}
.board__anim:nth-child(4) {
  animation-delay: 0.15s;
}
.board__anim:nth-child(5) {
  animation-delay: 0.2s;
}

@keyframes boardFadeUp {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.board__hero {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  flex-wrap: wrap;
}

.board__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  flex: 1;
  min-width: 220px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat__num {
  font-size: 1.2rem;
  font-weight: 750;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.stat__label {
  font-size: 0.78rem;
  color: var(--text-muted);
}

/* ---------- E1 节奏洞察 ---------- */
.insight {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: 0.86rem;
  line-height: 1.5;
}

.insight--ok {
  background: var(--brand-soft);
  color: var(--brand-active);
}

.insight--done {
  background: var(--success-soft);
  color: var(--success);
}

.insight--warn {
  background: var(--warning-soft);
  color: var(--warning);
}

.insight__icon {
  flex-shrink: 0;
}

/* ---------- 最近 7 天打卡热力 ---------- */
.streak__title {
  margin: 0 0 var(--space-2);
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--text-secondary);
}

.streak__row {
  display: flex;
  gap: 6px;
}

.streak__cell {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 7px 0;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: var(--text-muted);
  transition: background var(--transition);
}

.streak__cell--checked {
  background: var(--warning);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-sm);
}

.streak__cell--today {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}

.streak__num {
  font-size: 0.92rem;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.streak__wd {
  font-size: 0.66rem;
  opacity: 0.9;
}

/* ---------- 五阶段步骤条 ---------- */
.stages {
  display: flex;
  align-items: flex-start;
}

.stages__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  position: relative;
}

/* 连线：从上一节点中心连到本节点中心，压在节点之下 */
.stages__item:not(:first-child)::before {
  content: '';
  position: absolute;
  top: 10px;
  left: -50%;
  width: 100%;
  height: 2px;
  background: var(--border);
  z-index: 0;
}

.stages__item--filled:not(:first-child)::before {
  background: var(--success);
}

.stages__dot {
  position: relative;
  z-index: 1;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--surface-muted);
  border: 2px solid var(--border);
  color: var(--text-on-brand);
}

.stages__item--past .stages__dot {
  background: var(--success);
  border-color: var(--success);
}

.stages__item--active .stages__dot {
  background: var(--brand);
  border-color: var(--brand);
  box-shadow: 0 0 0 4px var(--brand-soft);
  animation: stagePulse 1.8s ease-in-out infinite;
}

@keyframes stagePulse {
  0%,
  100% {
    box-shadow: 0 0 0 4px var(--brand-soft);
  }
  50% {
    box-shadow: 0 0 0 7px var(--brand-soft);
  }
}

.stages__check {
  font-size: 0.66rem;
  font-weight: 800;
  line-height: 1;
}

.stages__label {
  font-size: 0.74rem;
  color: var(--text-muted);
  text-align: center;
}

.stages__item--active .stages__label {
  color: var(--brand);
  font-weight: 650;
}

.stages__item--past .stages__label {
  color: var(--text-secondary);
}

/* ---------- 周进度条 ---------- */
.weeks__title {
  margin: 0 0 var(--space-2);
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--text-secondary);
}

.weekbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: 8px;
}

.weekbar__name {
  flex-shrink: 0;
  width: 96px;
  font-size: 0.82rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

.weekbar--current .weekbar__name {
  color: var(--brand);
  font-weight: 650;
}

.weekbar__now {
  display: inline-block;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 0.66rem;
  font-weight: 700;
  vertical-align: middle;
}

.weekbar__track {
  position: relative;
  flex: 1;
  height: 10px;
  border-radius: 999px;
  background: var(--surface-muted);
  overflow: hidden;
}

.weekbar__fill {
  position: absolute;
  inset: 0 auto 0 0;
  height: 100%;
  background: var(--brand);
  border-radius: 999px;
  transition: width 0.5s ease;
  z-index: 1;
}

.weekbar--complete .weekbar__fill {
  background: var(--success);
}

.weekbar__count {
  flex-shrink: 0;
  width: 52px;
  text-align: right;
  font-size: 0.8rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.weekbar__tick {
  color: var(--success);
  font-weight: 700;
  margin-right: 2px;
}

/* 无障碍：系统偏好「减少动态效果」时关闭一切进度动画与过渡 */
@media (prefers-reduced-motion: reduce) {
  .board__anim {
    animation: none;
  }
  .stages__item--active .stages__dot {
    animation: none;
  }
  .weekbar__fill,
  .streak__cell {
    transition: none;
  }
}
</style>
