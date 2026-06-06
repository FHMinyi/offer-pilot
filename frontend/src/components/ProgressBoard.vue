<script setup lang="ts">
// 进度看板（里程碑一正反馈可视化）：完成率环 + 关键数值胶囊 + 周进度条 + 五阶段步骤条。
// 按 B7「相对进度/完成度」：只展示进步类数字，不报 Offer 概率。
import { computed } from 'vue'
import type { JourneyState, ProgressSummary } from '../types'
import ScoreRing from './ui/ScoreRing.vue'
import { STAGE_LABEL, STAGE_ORDER } from '../shared/journey'

const props = defineProps<{
  progress: ProgressSummary
  journey?: JourneyState | null
}>()

const ratePct = computed(() => Math.round((props.progress.completion_rate || 0) * 100))
const maxWeekTotal = computed(() =>
  Math.max(1, ...props.progress.week_progress.map((w) => w.total)),
)
const currentStageIndex = computed(() => {
  const s = props.journey?.stage
  const i = s ? STAGE_ORDER.indexOf(s) : -1
  return i
})
</script>

<template>
  <div class="board stack">
    <div class="board__hero">
      <ScoreRing :score="ratePct" :size="120" caption="完成率" />
      <div class="board__stats">
        <div class="stat">
          <span class="stat__num">{{ progress.done_tasks }}/{{ progress.total_tasks }}</span>
          <span class="stat__label">已完成任务</span>
        </div>
        <div class="stat">
          <span class="stat__num">第 {{ progress.current_week }} 周</span>
          <span class="stat__label">当前进度</span>
        </div>
        <div class="stat">
          <span class="stat__num">🔥 {{ progress.current_streak }}</span>
          <span class="stat__label">连续打卡（天）</span>
        </div>
        <div class="stat">
          <span class="stat__num">{{ progress.longest_streak }}</span>
          <span class="stat__label">最长连续</span>
        </div>
      </div>
    </div>

    <!-- 五阶段步骤条（高亮当前阶段） -->
    <div v-if="journey" class="stages" aria-label="旅程阶段">
      <div
        v-for="(st, i) in STAGE_ORDER"
        :key="st"
        class="stages__item"
        :class="{
          'stages__item--active': i === currentStageIndex,
          'stages__item--past': i < currentStageIndex,
        }"
      >
        <span class="stages__dot" aria-hidden="true" />
        <span class="stages__label">{{ STAGE_LABEL[st] }}</span>
      </div>
    </div>

    <!-- 周进度条 -->
    <div v-if="progress.week_progress.length" class="weeks">
      <p class="weeks__title">各周完成度</p>
      <div v-for="w in progress.week_progress" :key="w.week" class="weekbar">
        <span class="weekbar__name">第 {{ w.week }} 周</span>
        <div class="weekbar__track">
          <div
            class="weekbar__fill"
            :style="{ width: `${(w.done / Math.max(1, w.total)) * 100}%` }"
          />
          <!-- 轨道整体宽度按该周任务量相对最大周缩放，直观体现各周工作量差异 -->
          <span
            class="weekbar__scale"
            :style="{ width: `${(w.total / maxWeekTotal) * 100}%` }"
            aria-hidden="true"
          />
        </div>
        <span class="weekbar__count">{{ w.done }}/{{ w.total }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.board {
  gap: var(--space-5);
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

/* ---------- 五阶段步骤条 ---------- */
.stages {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.stages__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  position: relative;
}

.stages__dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--surface-muted);
  border: 2px solid var(--border);
}

.stages__item--past .stages__dot {
  background: var(--success);
  border-color: var(--success);
}

.stages__item--active .stages__dot {
  background: var(--brand);
  border-color: var(--brand);
  box-shadow: 0 0 0 4px var(--brand-soft);
}

.stages__label {
  font-size: 0.74rem;
  color: var(--text-muted);
}

.stages__item--active .stages__label {
  color: var(--brand);
  font-weight: 650;
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
  width: 56px;
  font-size: 0.82rem;
  color: var(--text-secondary);
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

.weekbar__scale {
  position: absolute;
  inset: 0 auto 0 0;
  height: 100%;
  background: transparent;
}

.weekbar__count {
  flex-shrink: 0;
  width: 44px;
  text-align: right;
  font-size: 0.8rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
