<script setup lang="ts">
// 进度看板（路由 /dashboard）：聚合当前旅程的完成度 / streak / 周进度 / 阶段。
import { computed, onMounted, ref, watch } from 'vue'
import { getJourney, getProgress } from '../api/client'
import type { JourneyState, ProgressSummary } from '../types'
import { progressCache, progressChanged } from '../shared/appState'
import AppCard from '../components/ui/AppCard.vue'
import ProgressBoard from '../components/ProgressBoard.vue'

const journey = ref<JourneyState | null>(null)
const progress = ref<ProgressSummary | null>(null)
const loading = ref(true)
const error = ref('')

const planLink = computed(() =>
  journey.value?.analysis_run_id != null ? `/plan/${journey.value.analysis_run_id}` : null,
)

onMounted(load)
// 勾选/打卡后（progressChanged +1）惰性重拉
watch(progressChanged, load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [j, p] = await Promise.all([getJourney(), getProgress()])
    journey.value = j
    progress.value = p
    // 写入共享缓存，供 SideNav streak 角标复用
    progressCache.value = p
    progressCache.loadedAt = Date.now()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载进度失败'
  } finally {
    loading.value = false
  }
}

const hasData = computed(() => !!progress.value && progress.value.total_tasks > 0)
</script>

<template>
  <div class="dash-view stack">
    <div class="topbar">
      <RouterLink class="back-link" :to="{ name: 'new' }">← 返回对话</RouterLink>
      <RouterLink v-if="planLink" class="back-link" :to="planLink">去执行计划 →</RouterLink>
    </div>

    <h2 class="dash-title">我的进度</h2>

    <AppCard v-if="loading">
      <div class="placeholder">
        <span class="spinner" aria-hidden="true" />
        <span class="muted">正在加载进度…</span>
      </div>
    </AppCard>

    <AppCard v-else-if="error">
      <div class="placeholder">
        <p class="placeholder__title">加载失败</p>
        <p class="muted">{{ error }}</p>
        <button class="btn" type="button" @click="load">重试</button>
      </div>
    </AppCard>

    <AppCard v-else-if="!hasData">
      <div class="placeholder">
        <p class="placeholder__title">还没有进行中的计划</p>
        <p class="muted">先在对话里完成一次匹配分析并生成学习方案，这里会显示你的完成度与坚持天数。</p>
        <RouterLink class="btn btn--primary" :to="{ name: 'new' }">去生成方案</RouterLink>
      </div>
    </AppCard>

    <AppCard v-else>
      <ProgressBoard :progress="progress!" :journey="journey" />
    </AppCard>
  </div>
</template>

<style scoped>
.dash-view {
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

.dash-title {
  margin: 0;
  font-size: 1.3rem;
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
