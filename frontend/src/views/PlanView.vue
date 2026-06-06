<script setup lang="ts">
// 活计划页（路由 /plan/:runId）：把某次分析物化出的可勾选任务 + 今日打卡串成执行闭环。
// runId = analysis_run_id（与 ChatView currentRunId、/result/:id 同源）。
import { computed, onMounted, ref } from 'vue'
import { getJourney, getProgress, listCheckIns, listTasks } from '../api/client'
import type { CheckIn, JourneyState, ProgressSummary, Task } from '../types'
import { localTodayIso, STAGE_LABEL } from '../shared/journey'
import { notifyProgressChanged } from '../shared/appState'
import AppCard from '../components/ui/AppCard.vue'
import ScoreRing from '../components/ui/ScoreRing.vue'
import TaskChecklist from '../components/TaskChecklist.vue'
import CheckInCard from '../components/CheckInCard.vue'

const props = defineProps<{ runId: string }>()

const tasks = ref<Task[]>([])
const journey = ref<JourneyState | null>(null)
const progress = ref<ProgressSummary | null>(null)
const todayCheckin = ref<CheckIn | null>(null)
const loading = ref(true)
const error = ref('')
const flash = ref('')

const runIdNum = computed(() => Number(props.runId))
const doneTaskIds = computed(() => tasks.value.filter((t) => t.status === 'done').map((t) => t.id))
const ratePct = computed(() => Math.round((progress.value?.completion_rate || 0) * 100))

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  if (!Number.isFinite(runIdNum.value) || runIdNum.value <= 0) {
    error.value = '无效的计划编号'
    loading.value = false
    return
  }
  try {
    const today = localTodayIso()
    const [t, j, p, ci] = await Promise.all([
      listTasks({ analysis_run_id: runIdNum.value }),
      getJourney(),
      getProgress(),
      listCheckIns({ start: today, end: today }),
    ])
    tasks.value = t
    journey.value = j
    progress.value = p
    todayCheckin.value = ci[0] ?? null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载计划失败'
  } finally {
    loading.value = false
  }
}

async function refreshProgress(): Promise<void> {
  try {
    progress.value = await getProgress()
    notifyProgressChanged()
  } catch {
    /* 进度刷新失败不打扰：勾选/打卡本体已成功 */
  }
}

function onTaskChanged(): void {
  void refreshProgress()
}

function onCheckinSaved(ci: CheckIn): void {
  todayCheckin.value = ci
  flash.value = '已记录今日打卡 🎉'
  void refreshProgress()
  window.setTimeout(() => (flash.value = ''), 2400)
}

function onError(msg: string): void {
  flash.value = msg
  window.setTimeout(() => (flash.value = ''), 3000)
}
</script>

<template>
  <div class="plan-view stack">
    <div class="topbar">
      <RouterLink class="back-link" :to="{ name: 'new' }">← 返回对话</RouterLink>
      <RouterLink class="back-link" to="/dashboard">我的进度 →</RouterLink>
    </div>

    <p v-if="flash" class="flash">{{ flash }}</p>

    <AppCard v-if="loading">
      <div class="placeholder">
        <span class="spinner" aria-hidden="true" />
        <span class="muted">正在加载执行计划…</span>
      </div>
    </AppCard>

    <AppCard v-else-if="error">
      <div class="placeholder">
        <p class="placeholder__title">加载失败</p>
        <p class="muted">{{ error }}</p>
        <button class="btn" type="button" @click="load">重试</button>
      </div>
    </AppCard>

    <AppCard v-else-if="!tasks.length">
      <div class="placeholder">
        <p class="placeholder__title">这份分析还没有可执行任务</p>
        <p class="muted">先在对话里完成一次匹配分析并生成学习方案，任务会自动出现在这里。</p>
        <RouterLink class="btn btn--primary" :to="{ name: 'new' }">去生成方案</RouterLink>
      </div>
    </AppCard>

    <template v-else>
      <header class="plan-head">
        <div>
          <h2 class="plan-head__title">执行计划</h2>
          <p class="plan-head__meta">
            <span v-if="journey?.target_role">🎯 {{ journey.target_role }}</span>
            <span v-if="journey">· {{ STAGE_LABEL[journey.stage] }}</span>
            <span v-if="progress">· 第 {{ progress.current_week }} 周</span>
          </p>
        </div>
        <div class="plan-head__ring">
          <ScoreRing :score="ratePct" :size="64" :stroke="6" caption="完成率" />
        </div>
      </header>

      <div class="plan-grid">
        <AppCard class="plan-grid__main">
          <TaskChecklist :tasks="tasks" @changed="onTaskChanged" @error="onError" />
        </AppCard>
        <AppCard class="plan-grid__aside">
          <CheckInCard
            :completed-task-ids="doneTaskIds"
            :initial="todayCheckin"
            @saved="onCheckinSaved"
            @error="onError"
          />
        </AppCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.plan-view {
  gap: var(--space-4);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.back-link {
  font-weight: 550;
  color: var(--text-secondary);
}

.back-link:hover {
  color: var(--brand);
}

.flash {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.86rem;
}

.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.plan-head__title {
  margin: 0;
  font-size: 1.2rem;
}

.plan-head__meta {
  margin: 4px 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.84rem;
  color: var(--text-muted);
}

.plan-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
  gap: var(--space-4);
  align-items: start;
}

@media (max-width: 860px) {
  .plan-grid {
    grid-template-columns: 1fr;
  }
}

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.placeholder__title {
  margin: 0;
  font-weight: 650;
  color: var(--text);
}

.spinner {
  width: 26px;
  height: 26px;
  border: 3px solid var(--surface-muted);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
