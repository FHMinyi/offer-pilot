<script setup lang="ts">
// 活计划页（路由 /plan/:runId）：把某次分析物化出的可勾选任务 + 今日打卡串成执行闭环。
// runId = analysis_run_id（与 ChatView currentRunId、/result/:id 同源）。
import { computed, onMounted, ref } from 'vue'
import { getJourney, getProgress, listCheckIns, listTasks, replanJourney } from '../api/client'
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
const replanning = ref(false)

const runIdNum = computed(() => Number(props.runId))
const doneTaskIds = computed(() => tasks.value.filter((t) => t.status === 'done').map((t) => t.id))
const ratePct = computed(() => Math.round((progress.value?.completion_rate || 0) * 100))

const todayIso = localTodayIso()
const isActive = (t: Task) => t.status === 'todo' || t.status === 'doing'
// 今日待办 + 逾期未完成（逾期在「结算」后会被顺延到今天起）
const todayTasks = computed(() => tasks.value.filter((t) => isActive(t) && t.planned_date === todayIso))
const overdueTasks = computed(() =>
  tasks.value.filter((t) => isActive(t) && t.planned_date && t.planned_date < todayIso),
)

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

/** 静默刷新任务+旅程+进度（打卡/重排后后端已变更日程，需重拉）。 */
async function quietRefresh(): Promise<void> {
  try {
    const [t, j, p] = await Promise.all([
      listTasks({ analysis_run_id: runIdNum.value }),
      getJourney(),
      getProgress(),
    ])
    tasks.value = t
    journey.value = j
    progress.value = p
    notifyProgressChanged()
  } catch {
    /* 刷新失败不打扰 */
  }
}

function showFlash(msg: string, ms = 2800): void {
  flash.value = msg
  window.setTimeout(() => (flash.value = ''), ms)
}

function onCheckinSaved(ci: CheckIn): void {
  todayCheckin.value = ci
  // 打卡=每日结算，后端已自动顺延/重组，重拉任务展示自适应结果
  void quietRefresh()
  showFlash('已记录今日打卡 🎉 计划已按进度自动重排')
}

/** 手动「结算今天并重排」：顺延逾期、重组剩余日程。 */
async function settleToday(): Promise<void> {
  if (!journey.value) return
  replanning.value = true
  try {
    const res = await replanJourney(journey.value.id, { settle: true, today: localTodayIso() })
    tasks.value = res.tasks
    journey.value = res.journey
    const carried = Number((res.journey.signals as { carried_over?: number })?.carried_over ?? 0)
    showFlash(
      carried > 0 ? `已重排：顺延 ${carried} 条未完成任务到今天起` : '已按进度重排日程 ✅',
    )
    void refreshProgress()
  } catch (err) {
    onError(err instanceof Error ? err.message : '重排失败')
  } finally {
    replanning.value = false
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

function onError(msg: string): void {
  showFlash(msg, 3000)
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

      <!-- 今日任务：动态再规划的主舞台（结算 → 顺延逾期 + 重组日程） -->
      <AppCard class="plan-today">
        <div class="plan-today__head">
          <span class="plan-today__title">📅 今日任务（{{ todayTasks.length }}）</span>
          <button class="btn btn--primary" type="button" :disabled="replanning" @click="settleToday">
            {{ replanning ? '重排中…' : '结算今天并重排' }}
          </button>
        </div>
        <p v-if="overdueTasks.length" class="plan-today__overdue">
          ⚠ {{ overdueTasks.length }} 条逾期未完成——点「结算」自动顺延到今天起并重组日程
        </p>
        <TaskChecklist
          v-if="todayTasks.length || overdueTasks.length"
          :tasks="[...overdueTasks, ...todayTasks]"
          flat
          @changed="onTaskChanged"
          @error="onError"
        />
        <p v-else class="muted">今天没有排定任务，去下方看看整份计划吧。</p>
        <p v-if="journey?.last_replanned_at" class="plan-today__stamp">
          🔄 上次重排：{{ fmtTime(journey.last_replanned_at) }}
        </p>
      </AppCard>

      <div class="plan-grid">
        <AppCard class="plan-grid__main">
          <TaskChecklist :tasks="tasks" show-date @changed="onTaskChanged" @error="onError" />
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

.plan-today__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.plan-today__title {
  font-weight: 700;
  font-size: 1rem;
}

.plan-today__overdue {
  margin: 0 0 var(--space-2);
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--surface-muted);
  border-left: 3px solid var(--warning);
  color: var(--warning);
  font-size: 0.84rem;
}

.plan-today__stamp {
  margin: var(--space-2) 0 0;
  font-size: 0.76rem;
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
