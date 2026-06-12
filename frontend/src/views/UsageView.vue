<script setup lang="ts">
// 用量统计页（路由 /usage）：token 用量时序 + 缓存命中率 + 按模型/功能汇总。
// 仿 DashboardView：stack 布局 + topbar + 卡片 + loading/error/空三态。
//
// 三组 segmented 控件：
//   粒度  天/周/月 → granularity（day/week/month）
//   维度  总计/按模型/按功能 → group_by（none/model/path）
//   指标  Token 用量/缓存命中率% → metric（tokens/hitRate）
//
// 请求策略：
//   · 时序：随「粒度 / 维度 / 筛选」变化重拉；指标切换（tokens↔hitRate）不重拉，
//     命中率从同一份 series 派生（图表组件内计算）。带 Map 内存缓存（键=粒度|维度|筛选）。
//   · 汇总：仅随「筛选」变化重拉（与粒度/维度无关）。
import { computed, onMounted, ref, watch } from 'vue'
import { fetchUsageSummary, fetchUsageTimeseries } from '../api/client'
import type {
  UsageFilters,
} from '../api/client'
import type {
  UsageGranularity,
  UsageGroupBy,
  UsageMetric,
  UsageSummary,
  UsageTimeseries,
} from '../types'
import AppCard from '../components/ui/AppCard.vue'
import UsageBarChart from '../components/usage/UsageBarChart.vue'
import UsageStatTable from '../components/usage/UsageStatTable.vue'

// ---------- segmented 控件状态 ----------
const granularity = ref<UsageGranularity>('day')
const groupBy = ref<UsageGroupBy>('none')
const metric = ref<UsageMetric>('tokens')

const granularityOptions: { value: UsageGranularity; label: string }[] = [
  { value: 'day', label: '天' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
]
const groupByOptions: { value: UsageGroupBy; label: string }[] = [
  { value: 'none', label: '总计' },
  { value: 'model', label: '按模型' },
  { value: 'path', label: '按功能' },
]
const metricOptions: { value: UsageMetric; label: string }[] = [
  { value: 'tokens', label: 'Token 用量' },
  { value: 'hitRate', label: '缓存命中率%' },
]

// ---------- 筛选（本期不暴露 UI，预留入参；保持 API 形状完整） ----------
const filters = ref<UsageFilters>({})

// ---------- 数据 ----------
const timeseries = ref<UsageTimeseries | null>(null)
const summary = ref<UsageSummary | null>(null)
const loadingTs = ref(true)
const loadingSum = ref(true)
const errorTs = ref('')
const errorSum = ref('')

// 时序内存缓存：键 = 粒度|维度|筛选序列化。
const tsCache = new Map<string, UsageTimeseries>()
function tsKey(): string {
  return [granularity.value, groupBy.value, JSON.stringify(filters.value)].join('|')
}

// 拉时序（带缓存）。维度 none 也带 group_by=none（后端返回单序列 all/全部）。
async function loadTimeseries(): Promise<void> {
  const key = tsKey()
  const cached = tsCache.get(key)
  if (cached) {
    timeseries.value = cached
    loadingTs.value = false
    errorTs.value = ''
    return
  }
  loadingTs.value = true
  errorTs.value = ''
  try {
    const data = await fetchUsageTimeseries(granularity.value, {
      group_by: groupBy.value,
      ...filters.value,
    })
    tsCache.set(key, data)
    timeseries.value = data
  } catch (err) {
    errorTs.value = err instanceof Error ? err.message : '加载用量时序失败'
  } finally {
    loadingTs.value = false
  }
}

// 拉汇总（仅随筛选变化）。
async function loadSummary(): Promise<void> {
  loadingSum.value = true
  errorSum.value = ''
  try {
    summary.value = await fetchUsageSummary(filters.value)
  } catch (err) {
    errorSum.value = err instanceof Error ? err.message : '加载用量汇总失败'
  } finally {
    loadingSum.value = false
  }
}

onMounted(() => {
  void loadTimeseries()
  void loadSummary()
})

// 粒度 / 维度变 → 重拉时序（指标切换不触发）。
watch([granularity, groupBy], () => void loadTimeseries())
// 筛选变 → 时序 + 汇总都重拉。
watch(
  filters,
  () => {
    void loadTimeseries()
    void loadSummary()
  },
  { deep: true },
)

// 总计卡：四个数字 + 命中率。
const totalHitRate = computed<string>(() => {
  const s = summary.value
  if (!s) return '—'
  const denom = s.total_input_hit + s.total_input_miss
  return denom > 0 ? `${Math.round((s.total_input_hit / denom) * 100)}%` : '—'
})

function fmt(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  if (v < 1000) return String(v)
  const k = v / 1000
  return `${k >= 100 ? Math.round(k) : Number(k.toFixed(1))}k`
}

// 是否有汇总数据（决定汇总卡是否显示空态）。
const hasSummary = computed(() => (summary.value?.total_calls ?? 0) > 0)
</script>

<template>
  <div class="usage-view stack">
    <div class="topbar">
      <RouterLink class="back-link" :to="{ name: 'new' }">← 返回对话</RouterLink>
      <RouterLink class="back-link" :to="{ name: 'dashboard' }">我的进度 →</RouterLink>
    </div>

    <h2 class="usage-title">用量统计</h2>
    <p class="usage-sub muted">
      三类 token 全链路统一口径：命中（缓存）/ 未命中 / 输出。命中率越高越省钱——
      把固定指令前置可提升 prefix cache 命中。
    </p>

    <!-- ============ segmented 控件 ============ -->
    <div class="controls">
      <div class="seg" role="tablist" aria-label="时间粒度">
        <button
          v-for="o in granularityOptions"
          :key="o.value"
          type="button"
          class="seg__tab"
          :class="{ 'seg__tab--on': granularity === o.value }"
          role="tab"
          :aria-selected="granularity === o.value"
          @click="granularity = o.value"
        >
          {{ o.label }}
        </button>
      </div>

      <div class="seg" role="tablist" aria-label="聚合维度">
        <button
          v-for="o in groupByOptions"
          :key="o.value"
          type="button"
          class="seg__tab"
          :class="{ 'seg__tab--on': groupBy === o.value }"
          role="tab"
          :aria-selected="groupBy === o.value"
          @click="groupBy = o.value"
        >
          {{ o.label }}
        </button>
      </div>

      <div class="seg" role="tablist" aria-label="图表指标">
        <button
          v-for="o in metricOptions"
          :key="o.value"
          type="button"
          class="seg__tab"
          :class="{ 'seg__tab--on': metric === o.value }"
          role="tab"
          :aria-selected="metric === o.value"
          @click="metric = o.value"
        >
          {{ o.label }}
        </button>
      </div>
    </div>

    <!-- ============ 顶部双表（按模型 / 按功能） ============ -->
    <AppCard v-if="loadingSum">
      <div class="placeholder">
        <span class="spinner" aria-hidden="true" />
        <span class="muted">正在加载汇总…</span>
      </div>
    </AppCard>

    <AppCard v-else-if="errorSum">
      <div class="placeholder">
        <p class="placeholder__title">加载失败</p>
        <p class="muted">{{ errorSum }}</p>
        <button class="btn" type="button" @click="loadSummary">重试</button>
      </div>
    </AppCard>

    <AppCard v-else-if="!hasSummary">
      <div class="placeholder">
        <p class="placeholder__title">还没有用量记录</p>
        <p class="muted">先在对话里发起一次分析或聊天，这里会出现 token 用量与缓存命中统计。</p>
        <RouterLink class="btn btn--primary" :to="{ name: 'new' }">去对话</RouterLink>
      </div>
    </AppCard>

    <template v-else>
      <!-- 总计卡 -->
      <AppCard>
        <div class="totals">
          <div class="totals__item">
            <span class="totals__num">{{ fmt((summary?.total_input_hit ?? 0) + (summary?.total_input_miss ?? 0) + (summary?.total_output ?? 0)) }}</span>
            <span class="totals__lbl">总 token</span>
          </div>
          <div class="totals__item">
            <span class="totals__num" style="color: var(--tok-hit)">{{ fmt(summary?.total_input_hit ?? 0) }}</span>
            <span class="totals__lbl">命中</span>
          </div>
          <div class="totals__item">
            <span class="totals__num" style="color: var(--tok-miss)">{{ fmt(summary?.total_input_miss ?? 0) }}</span>
            <span class="totals__lbl">未命中</span>
          </div>
          <div class="totals__item">
            <span class="totals__num" style="color: var(--tok-output)">{{ fmt(summary?.total_output ?? 0) }}</span>
            <span class="totals__lbl">输出</span>
          </div>
          <div class="totals__item">
            <span class="totals__num">{{ totalHitRate }}</span>
            <span class="totals__lbl">命中率</span>
          </div>
          <div class="totals__item">
            <span class="totals__num">{{ summary?.total_calls ?? 0 }}</span>
            <span class="totals__lbl">调用次数</span>
          </div>
        </div>
      </AppCard>

      <!-- 双表 -->
      <AppCard>
        <div class="tables">
          <UsageStatTable title="按模型" :rows="summary?.by_model ?? []" />
          <UsageStatTable title="按功能" :rows="summary?.by_path ?? []" />
        </div>
      </AppCard>
    </template>

    <!-- ============ 中部图表 ============ -->
    <AppCard v-if="loadingTs">
      <div class="placeholder">
        <span class="spinner" aria-hidden="true" />
        <span class="muted">正在加载时序…</span>
      </div>
    </AppCard>

    <AppCard v-else-if="errorTs">
      <div class="placeholder">
        <p class="placeholder__title">加载失败</p>
        <p class="muted">{{ errorTs }}</p>
        <button class="btn" type="button" @click="loadTimeseries">重试</button>
      </div>
    </AppCard>

    <AppCard v-else-if="timeseries">
      <UsageBarChart
        :metric="metric"
        :series="timeseries.series"
        :bucket-starts="timeseries.bucket_starts"
        :granularity="timeseries.granularity"
      />
    </AppCard>
  </div>
</template>

<style scoped>
.usage-view {
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

.usage-title {
  margin: 0;
  font-size: 1.3rem;
}

.usage-sub {
  margin: 0;
  font-size: 0.84rem;
  max-width: 60ch;
}

/* ---------- segmented 控件（药丸 tab，仿 MasteryDrawer，自定义 scoped 样式） ---------- */
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.seg {
  display: inline-flex;
  gap: var(--space-2);
  padding: 3px;
  border-radius: var(--radius);
  background: var(--surface-muted);
}

.seg__tab {
  padding: 7px 14px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.84rem;
  font-weight: 550;
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}

.seg__tab--on {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--shadow-sm);
}

/* ---------- 总计卡 ---------- */
.totals {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
}

.totals__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 80px;
}

.totals__num {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.totals__lbl {
  font-size: 0.76rem;
  color: var(--text-muted);
}

/* ---------- 双表：宽屏并排，窄屏堆叠 ---------- */
.tables {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

@media (max-width: 760px) {
  .tables {
    grid-template-columns: 1fr;
  }
}

/* ---------- 三态占位（复用 DashboardView 视觉） ---------- */
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
