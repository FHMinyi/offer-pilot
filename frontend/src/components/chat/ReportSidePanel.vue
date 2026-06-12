<script setup lang="ts">
// 右栏报告侧边面板（纯展示）——最新匹配分析的【紧凑摘要】+ 学习方案预览：
//   · 已出方案：分周路线预览（前 3 周）+ 简述（方案依据）+ 匹配度次级一行 + 打卡入口；
//   · 仅匹配分析：环形匹配度 + 目标岗位 + 简述 + 「下一步生成方案」提示；
//   · 主按钮经 view-full 交父级跳转 /result/:id（需先兜底落库拿会话 id）。
//
// 编排状态全部留在 ChatView：开合（v-if，本面板随隐藏频繁卸载）、reportNav
// 同步与清理、openReportSignal 监听——放在这里会随卸载断掉侧栏重开链路。
// 本组件只暴露 focusTop()：面板滚到顶 + 短暂高亮（消息流 chip 点击 / SideNav
// 入口的视线引导；父级先确保面板可见、等 nextTick 挂载后再调用）。
import { computed, nextTick, ref } from 'vue'
import type { AssistantBlock } from '../../shared/chatModel'
import type { WeekItem } from '../../types'
import ScoreRing from '../ui/ScoreRing.vue'

const props = defineProps<{
  /** 最新报告块（父级 findLastReportBlock 的结果；面板仅在其存在时被渲染） */
  report: Extract<AssistantBlock, { kind: 'report' }>
  /** 是否已生成学习方案（决定以「学习方案」还是「匹配分析」为主角） */
  hasPlan: boolean
  /** 最近一次匹配分析 id（打卡入口 /plan/:id；可能尚未就绪则不渲染入口） */
  currentRunId: number | null
}>()

const emit = defineEmits<{
  /** 「隐藏」按钮：父级收起右栏（重新展开经 SideNav 入口） */
  (e: 'hide'): void
  /** 主按钮：父级跳转完整报告页 /result/:id（全展开） */
  (e: 'view-full'): void
}>()

// ---------- 派生展示数据 ----------
// 报告里的学习路线（周计划，按周号升序）；为空表示尚未进入第二步生成计划。
const roadmap = computed<WeekItem[]>(() => {
  const r = props.report.result.roadmap
  return Array.isArray(r) ? [...r].sort((a, b) => a.week - b.week) : []
})
// 学习方案预览：取前 3 周（周号 + 该周聚焦技能前 3 项）。
const planPreview = computed(() =>
  roadmap.value.slice(0, 3).map((w) => ({
    week: w.week,
    focus: (w.focus_skills ?? []).slice(0, 3),
  })),
)
// 主按钮文案：已出方案 → 查看完整学习方案；仅匹配分析 → 查看完整报告。
const fullReportCtaLabel = computed(() =>
  props.hasPlan ? '查看完整学习方案' : '查看完整报告',
)

// ---------- 滚顶高亮（focusTop，父级经 ref 调用） ----------
// 面板根元素引用（滚到顶 / 滚入视口用）。
const panelRef = ref<HTMLElement | null>(null)
// 短暂高亮态与重置计时器。组件随 v-if 卸载时计时器不主动清理：
// 残留回调只写本地 ref，无副作用（与拆分前计时器留在 ChatView 的行为一致）。
const highlight = ref(false)
let highlightTimer: ReturnType<typeof setTimeout> | undefined

// 让面板滚到顶并短暂高亮（提示「报告在这里」；连续调用会重置计时器）。
function focusTop(): void {
  const el = panelRef.value
  if (el) {
    // 面板自身滚到顶；并把面板滚入视口（窄屏堆叠在下方时尤为有用）
    el.scrollTop = 0
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
  // 触发一次短暂高亮（先复位再置位，支持连续点击重新起算）
  highlight.value = false
  void nextTick(() => {
    highlight.value = true
    if (highlightTimer) clearTimeout(highlightTimer)
    highlightTimer = setTimeout(() => {
      highlight.value = false
    }, 1200)
  })
}

defineExpose({ focusTop })
</script>

<template>
  <div
    ref="panelRef"
    class="report-panel"
    :class="{ 'report-panel--flash': highlight }"
  >
    <!-- 顶部标题（已出方案 → 学习方案为主角；否则匹配分析）+ 隐藏按钮 -->
    <header class="report-panel__head">
      <span class="report-panel__title">
        <span class="report-panel__title-icon" aria-hidden="true">{{ hasPlan ? '🎓' : '📊' }}</span>
        {{ hasPlan ? '你的学习方案' : '匹配分析' }}
      </span>
      <button
        type="button"
        class="report-panel__hide"
        title="隐藏侧栏（聊天区占满宽度）"
        @click="emit('hide')"
      >
        隐藏
      </button>
    </header>

    <!-- ===== 已生成学习方案：以「分周学习路线」为主产出 ===== -->
    <template v-if="hasPlan">
      <div class="plan">
        <p class="plan__lead">
          <span class="plan__weeks">{{ roadmap.length }} 周</span>个性化学习路线<!--
          --><span v-if="report.result.target_role" class="plan__role">
            · {{ report.result.target_role }}</span>
        </p>
        <ul class="plan__list">
          <li v-for="w in planPreview" :key="w.week" class="plan__week">
            <span class="plan__week-no">第 {{ w.week }} 周</span>
            <span class="plan__week-focus">
              <template v-if="w.focus.length">{{ w.focus.join('、') }}</template>
              <template v-else>综合复盘 / 模拟面试</template>
            </span>
          </li>
        </ul>
        <p v-if="roadmap.length > planPreview.length" class="plan__more">
          …共 {{ roadmap.length }} 周完整计划，点下方查看
        </p>
      </div>

      <!-- 保留匹配分析简述，维持「方案依据」的上下文（多行截断，不喧宾夺主） -->
      <p
        v-if="report.result.summary"
        class="report-panel__summary report-panel__summary--compact"
      >
        {{ report.result.summary }}
      </p>

      <!-- 匹配度降为次级一行（环形 mini + 文案） -->
      <div class="report-panel__score-row">
        <ScoreRing :score="report.result.match_score" :size="44" :stroke="5" />
        <span class="report-panel__score-text">岗位匹配度 {{ report.result.match_score }}%</span>
      </div>
    </template>

    <!-- ===== 仅匹配分析：紧凑摘要 + 「下一步生成方案」提示 ===== -->
    <template v-else>
      <div class="report-panel__ring">
        <ScoreRing :score="report.result.match_score" :size="120" />
      </div>
      <p v-if="report.result.target_role" class="report-panel__role">
        <span class="report-panel__role-icon" aria-hidden="true">🎯</span>
        {{ report.result.target_role }}
      </p>
      <p v-if="report.result.summary" class="report-panel__summary">
        {{ report.result.summary }}
      </p>
      <p class="report-panel__next">
        <span aria-hidden="true">💡</span>
        回答上方 AI 的几个问题后，我会据此生成你的<strong>完整分周学习方案</strong>。
      </p>
    </template>

    <!-- 主按钮：文案随是否已出方案切换；均跳转 /result/:id 全展开（经父级） -->
    <button type="button" class="report-panel__cta" @click="emit('view-full')">
      {{ fullReportCtaLabel }}
      <span class="report-panel__cta-arrow" aria-hidden="true">→</span>
    </button>

    <!-- 已出方案：次级入口跳活计划页（可勾选任务 + 每日打卡），不触碰对话内核 -->
    <RouterLink
      v-if="hasPlan && currentRunId"
      class="report-panel__plan-link"
      :to="`/plan/${currentRunId}`"
    >
      📋 开始执行 / 每日打卡
    </RouterLink>
  </div>
</template>

<style scoped>
/* 报告【紧凑摘要】面板：sticky 贴顶的卡片，只摆要点（不内滚整份报告）；
   切换报告时短暂高亮。外层布局壳（.chat__right 宽度 / 堆叠）由 ChatView 负责。 */
.report-panel {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  /* 高亮过渡：box-shadow 渐隐 */
  transition: box-shadow 0.4s ease;
}

.report-panel--flash {
  box-shadow: 0 0 0 3px var(--brand-soft);
}

/* 顶部小标题行：标题 + 「隐藏」按钮 */
.report-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.report-panel__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
}

.report-panel__title-icon {
  font-size: 0.95em;
  line-height: 1;
}

.report-panel__hide {
  flex-shrink: 0;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    border-color var(--transition),
    color var(--transition),
    background var(--transition);
}

.report-panel__hide:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

/* 环形匹配度：居中摆放 */
.report-panel__ring {
  display: flex;
  justify-content: center;
  padding: var(--space-1) 0;
}

/* 目标岗位 */
.report-panel__role {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.report-panel__role-icon {
  flex-shrink: 0;
  font-size: 0.95em;
  line-height: 1;
}

/* 简述：多行截断（clamp 数行），避免把侧栏撑长 */
.report-panel__summary {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--text-secondary);
  /* 多行省略：最多 5 行 */
  display: -webkit-box;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 学习方案视图下的简述：更紧凑（3 行），作为方案依据的上下文，不抢占主体 */
.report-panel__summary--compact {
  -webkit-line-clamp: 3;
  line-clamp: 3;
  font-size: 0.84rem;
  color: var(--text-muted);
}

/* 「查看完整报告」主按钮 */
.report-panel__cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: var(--space-1);
  padding: 10px 16px;
  border: 1px solid var(--brand);
  border-radius: var(--radius);
  background: var(--brand);
  color: var(--text-on-brand);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition:
    background var(--transition),
    border-color var(--transition),
    transform var(--transition);
}

.report-panel__cta:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.report-panel__cta:active {
  transform: translateY(1px);
}

.report-panel__cta-arrow {
  font-size: 1em;
  line-height: 1;
}

/* 次级入口：跳活计划页（开始执行 / 每日打卡） */
.report-panel__plan-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: var(--space-2);
  padding: 8px 14px;
  border: 1px solid var(--brand-soft);
  border-radius: var(--radius);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.86rem;
  font-weight: 600;
  transition:
    border-color var(--transition),
    color var(--transition);
}

.report-panel__plan-link:hover {
  border-color: var(--brand);
  color: var(--brand);
}

/* ---------- 侧栏：学习方案（主产出）+ 匹配度次级 ---------- */
.plan {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.plan__lead {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--text-secondary);
}

.plan__weeks {
  font-size: 1.05rem;
  font-weight: 800;
  color: var(--brand);
  margin-right: 4px;
}

.plan__role {
  color: var(--text-muted);
}

.plan__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan__week {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}

.plan__week-no {
  flex-shrink: 0;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--brand-active);
}

.plan__week-focus {
  min-width: 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}

.plan__more {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-muted);
}

/* 匹配度次级一行（有学习方案时） */
.report-panel__score-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border);
}

.report-panel__score-text {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-secondary);
}

/* 「下一步生成方案」提示（仅匹配分析阶段） */
.report-panel__next {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.82rem;
  line-height: 1.55;
}

.report-panel__next strong {
  font-weight: 700;
}

/* ---------- 响应式 ---------- */
/* 窄屏（<960px，与 ChatView 的两栏堆叠断点一致）：
   紧凑摘要面板取消 sticky，随页面滚动堆叠在对话下方 */
@media (max-width: 960px) {
  .report-panel {
    position: static;
  }
}
</style>
