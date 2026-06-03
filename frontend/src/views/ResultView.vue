<script setup lang="ts">
// 分析结果页（路由 /result/:id）
// 职责：按 id 拉取一次分析记录 AnalysisRun，处理 loading/错误，
//       然后把 run.result 及其元信息交给可复用的 <AnalysisReport> 渲染。
// 报告主体的渲染与 Markdown 导出逻辑已全部抽到 AnalysisReport 组件中，
// 本视图不再重复实现。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { getAnalysis } from '../api/client'
import type { AnalysisRun } from '../types'
import AppCard from '../components/ui/AppCard.vue'
import AnalysisReport from '../components/AnalysisReport.vue'

// 路由参数 id 作为字符串 prop 传入（router 配置 props: true）
const props = defineProps<{ id: string }>()

const route = useRoute()

// 来源会话 id：由 ChatView「查看完整学习方案/报告」携带 ?from=<会话id> 传入。
// 有则左上角「返回」回到该对话（/?c=<id> 续聊态），否则回到主界面（新建）。
const fromConversationId = computed<number | null>(() => {
  const raw = route.query.from
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(id) && id > 0 ? id : null
})
const backTo = computed<RouteLocationRaw>(() =>
  fromConversationId.value != null
    ? { path: '/', query: { c: String(fromConversationId.value) } }
    : { name: 'new' },
)
const backLabel = computed(() =>
  fromConversationId.value != null ? '← 返回对话' : '← 返回新建',
)

// ---------- 数据加载状态 ----------
const run = ref<AnalysisRun | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(load)

/** 拉取分析记录；id 非法或请求失败时给出可读错误 */
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  run.value = null

  const numericId = Number(props.id)
  if (!Number.isFinite(numericId) || numericId <= 0) {
    error.value = '无效的分析编号'
    loading.value = false
    return
  }

  try {
    run.value = await getAnalysis(numericId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载分析结果失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="result-view stack">
    <!-- 顶部返回链接：来自对话时返回该对话续聊态，否则返回主界面 -->
    <div class="topbar">
      <RouterLink class="back-link" :to="backTo">{{ backLabel }}</RouterLink>
    </div>

    <!-- 加载占位 -->
    <AppCard v-if="loading">
      <div class="placeholder">
        <span class="spinner" aria-hidden="true" />
        <span class="muted">正在加载分析结果…</span>
      </div>
    </AppCard>

    <!-- 错误占位 -->
    <AppCard v-else-if="error">
      <div class="placeholder placeholder--error">
        <p class="placeholder__title">加载失败</p>
        <p class="muted">{{ error }}</p>
        <div class="row wrap placeholder__actions">
          <button class="btn" type="button" @click="load">重试</button>
          <RouterLink class="btn" :to="backTo">{{ backLabel.replace('← ', '') }}</RouterLink>
        </div>
      </div>
    </AppCard>

    <!-- 正常内容：交给可复用报告组件渲染 -->
    <!-- collapsible=false：完整报告页始终全展开，不显示展开/收起切换，
         也不显示「查看完整报告页」链接（本身已在该页）。 -->
    <AnalysisReport
      v-else-if="run"
      :result="run.result"
      :engine="run.engine"
      :target-role="run.target_role"
      :created-at="run.created_at"
      :run-id="run.id"
      :collapsible="false"
    />
  </div>
</template>

<style scoped>
.result-view {
  gap: var(--space-5);
}

/* 顶部返回 */
.topbar {
  display: flex;
  align-items: center;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: 550;
  color: var(--text-secondary);
}

.back-link:hover {
  color: var(--brand);
}

/* ---------- 占位（加载/错误） ---------- */
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.placeholder__title {
  font-weight: 650;
  color: var(--text);
}

.placeholder__actions {
  margin-top: var(--space-2);
  justify-content: center;
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
