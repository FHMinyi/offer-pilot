<script setup lang="ts">
// 左侧导航边栏（应用外壳的一部分，由 App.vue 挂载）。
// 承载原顶栏的全部职能：品牌 Logo、新对话、最近会话列表、历史记录入口。
//
// 形态：
//   · 宽屏：常驻左侧；可「折叠」成窄图标栏（sidebarCollapsed，持久化）。
//   · 窄屏：化为抽屉，由 App.vue 控制滑入/滑出（sidebarState.mobileOpen）。
//
// 协同（见 shared/appState）：
//   · 「新对话」→ requestNewChat() 通知 ChatView 重置 + 路由回到 '/'。
//   · 监听 conversationsChanged：ChatView 保存会话后自动刷新本列表。
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProgress, listConversations } from '../api/client'
import type { ConversationSummary } from '../types'
import {
  sidebarCollapsed,
  isWide,
  toggleSidebarCollapsed,
  closeMobileSidebar,
  requestNewChat,
  conversationsChanged,
  reportNav,
  requestOpenReport,
  progressCache,
  progressChanged,
} from '../shared/appState'

const route = useRoute()
const router = useRouter()

// 有效折叠：仅宽屏下「折叠成窄栏」生效；窄屏抽屉始终展示完整侧栏。
const effectiveCollapsed = computed(() => sidebarCollapsed.value && isWide.value)

// 最近会话列表（按更新时间倒序，仅取前若干条；「全部」走历史页）。
const conversations = ref<ConversationSummary[]>([])
const loadingList = ref(false)

// 最多在侧栏展示的会话条数（更多请进历史记录页）。
const MAX_ITEMS = 20

async function loadConversations(): Promise<void> {
  loadingList.value = true
  try {
    const list = await listConversations()
    conversations.value = list.slice(0, MAX_ITEMS)
  } catch {
    // 侧栏列表加载失败不打扰用户（顶层功能仍可用）
    conversations.value = []
  } finally {
    loadingList.value = false
  }
}

onMounted(loadConversations)
// ChatView 保存会话后 +1 → 刷新列表，让新会话/新标题即时出现
watch(conversationsChanged, loadConversations)

// 当前正在续聊的会话 id（来自 /?c=<id>）；用于高亮。
const activeId = computed<number | null>(() => {
  const raw = route.query.c
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(id) && id > 0 ? id : null
})

// 是否处于对话主界面（路由名 'new'，即 '/'）。
const onChat = computed(() => route.name === 'new')

// 「新对话」：通知 ChatView 重置 + 路由回到干净的 '/'。
function newChat(): void {
  requestNewChat()
  if (route.fullPath !== '/') void router.push('/')
  closeMobileSidebar()
}

// 打开某段会话续聊。
function openConversation(id: number): void {
  if (activeId.value !== id || route.name !== 'new') {
    void router.push({ path: '/', query: { c: String(id) } })
  }
  closeMobileSidebar()
}

// 点击 Logo 回到主页（等同新对话入口，但不强制重置，交给路由）。
function goHome(): void {
  if (route.fullPath !== '/') void router.push('/')
  closeMobileSidebar()
}

// 跳转历史记录全量页。
function goHistory(): void {
  if (route.name !== 'history') void router.push({ name: 'history' })
  closeMobileSidebar()
}

// 「我的进度」入口 + 🔥streak 角标（取自共享缓存，避免重复请求）。
const streak = computed(() => progressCache.value?.current_streak ?? 0)

async function loadProgress(): Promise<void> {
  try {
    const p = await getProgress()
    progressCache.value = p
    progressCache.loadedAt = Date.now()
  } catch {
    // 侧栏角标加载失败不打扰用户
  }
}
onMounted(loadProgress)
// 勾选/打卡后（progressChanged +1）刷新角标
watch(progressChanged, loadProgress)

// 跳转进度看板。
function goDashboard(): void {
  if (route.name !== 'dashboard') void router.push({ name: 'dashboard' })
  closeMobileSidebar()
}

// 跳转用量统计（token 用量 / 缓存命中率 / 按模型·功能汇总）。
function goUsage(): void {
  if (route.name !== 'usage') void router.push({ name: 'usage' })
  closeMobileSidebar()
}

// 「报告 / 学习方案」入口（取代原 ChatView 右下角悬浮角标）：
// 通过共享信号让 ChatView 展开并滚动高亮报告面板。仅在对话页且已有报告时显示。
function openReport(): void {
  requestOpenReport()
  closeMobileSidebar()
}
</script>

<template>
  <aside class="sidenav" :class="{ 'sidenav--collapsed': effectiveCollapsed }">
    <!-- 顶部：品牌 + 折叠按钮 -->
    <div class="sidenav__top">
      <button type="button" class="brand" title="OfferPilot · 返回主页" @click="goHome">
        <span class="brand__mark" aria-hidden="true">OP</span>
        <span v-if="!effectiveCollapsed" class="brand__text">
          <span class="brand__name">OfferPilot</span>
          <span class="brand__tagline">AI 求职规划</span>
        </span>
      </button>
      <button
        v-if="isWide"
        type="button"
        class="collapse-btn"
        :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
        :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
        @click="toggleSidebarCollapsed"
      >
        <span aria-hidden="true">{{ sidebarCollapsed ? '»' : '«' }}</span>
      </button>
    </div>

    <!-- 新对话 -->
    <button
      type="button"
      class="new-chat"
      :title="'开始一段全新对话'"
      @click="newChat"
    >
      <span class="new-chat__icon" aria-hidden="true">＋</span>
      <span v-if="!effectiveCollapsed" class="new-chat__text">新对话</span>
    </button>

    <!-- 当前对话的「报告 / 学习方案」入口：仅在对话页且已生成报告时显示。
         点击展开右侧报告面板并滚动高亮（取代原右下角悬浮角标，统一到左侧栏）。 -->
    <button
      v-if="onChat && reportNav.available"
      type="button"
      class="report-link"
      :class="{ 'report-link--active': reportNav.open }"
      :title="reportNav.hasPlan ? '查看本次学习方案' : '查看本次匹配分析'"
      @click="openReport"
    >
      <span class="report-link__icon" aria-hidden="true">{{ reportNav.hasPlan ? '🎓' : '📊' }}</span>
      <span v-if="!effectiveCollapsed" class="report-link__text">
        {{ reportNav.hasPlan ? '学习方案' : '匹配分析' }}
      </span>
    </button>

    <!-- 最近会话列表（折叠态隐藏，展开态滚动） -->
    <nav v-if="!effectiveCollapsed" class="convos" aria-label="最近会话">
      <p class="convos__title">最近会话</p>
      <ul v-if="conversations.length" class="convos__list">
        <li v-for="c in conversations" :key="c.id">
          <button
            type="button"
            class="convo"
            :class="{ 'convo--active': onChat && activeId === c.id }"
            :title="c.title"
            @click="openConversation(c.id)"
          >
            <span class="convo__icon" aria-hidden="true">💬</span>
            <span class="convo__text">{{ c.title || '未命名对话' }}</span>
          </button>
        </li>
      </ul>
      <p v-else-if="!loadingList" class="convos__empty">暂无会话，开始你的第一段对话吧。</p>
    </nav>

    <!-- 折叠态：仅留一个「会话/历史」图标入口 -->
    <button
      v-else
      type="button"
      class="rail-btn"
      title="历史记录"
      aria-label="历史记录"
      @click="goHistory"
    >
      <span aria-hidden="true">🕘</span>
    </button>

    <!-- 底部：我的进度 + 历史记录全量入口 + 版本信息 -->
    <div class="sidenav__foot">
      <button
        v-if="!effectiveCollapsed"
        type="button"
        class="foot-link"
        :class="{ 'foot-link--active': route.name === 'dashboard' }"
        title="查看完成度与坚持天数"
        @click="goDashboard"
      >
        <span class="foot-link__icon" aria-hidden="true">📈</span>
        我的进度
        <span v-if="streak > 0" class="streak-badge" :title="`已连续打卡 ${streak} 天`">
          🔥{{ streak }}
        </span>
      </button>
      <button
        v-else
        type="button"
        class="rail-btn rail-btn--foot"
        title="我的进度"
        aria-label="我的进度"
        @click="goDashboard"
      >
        <span aria-hidden="true">📈</span>
      </button>
      <!-- 用量统计入口（token 用量 / 缓存命中率） -->
      <button
        v-if="!effectiveCollapsed"
        type="button"
        class="foot-link"
        :class="{ 'foot-link--active': route.name === 'usage' }"
        title="token 用量与缓存命中率统计"
        @click="goUsage"
      >
        <span class="foot-link__icon" aria-hidden="true">📊</span>
        用量
      </button>
      <button
        v-else
        type="button"
        class="rail-btn rail-btn--foot"
        title="用量统计"
        aria-label="用量统计"
        @click="goUsage"
      >
        <span aria-hidden="true">📊</span>
      </button>
      <button
        v-if="!effectiveCollapsed"
        type="button"
        class="foot-link"
        :class="{ 'foot-link--active': route.name === 'history' }"
        @click="goHistory"
      >
        <span class="foot-link__icon" aria-hidden="true">🕘</span>
        历史记录
      </button>
      <p v-if="!effectiveCollapsed" class="sidenav__ver">面向应届生 / 实习求职</p>
    </div>
  </aside>
</template>

<style scoped>
.sidenav {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 260px;
  flex-shrink: 0;
  padding: var(--space-4) var(--space-3);
  gap: var(--space-3);
  background: var(--surface);
  border-right: 1px solid var(--border);
  transition: width 0.18s ease;
}

.sidenav--collapsed {
  width: 64px;
  align-items: center;
  padding-left: var(--space-2);
  padding-right: var(--space-2);
}

/* ---------- 顶部品牌 + 折叠按钮 ---------- */
.sidenav__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.sidenav--collapsed .sidenav__top {
  flex-direction: column;
  gap: var(--space-2);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  min-width: 0;
}

.brand__mark {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius);
  background: var(--brand);
  color: var(--text-on-brand);
  font-weight: 800;
  font-size: 0.82rem;
  letter-spacing: 0.02em;
  box-shadow: var(--shadow-sm);
}

.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  min-width: 0;
}

.brand__name {
  font-weight: 750;
  font-size: 1rem;
  letter-spacing: -0.01em;
}

.brand__tagline {
  font-size: 0.74rem;
  color: var(--text-muted);
}

.collapse-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.9rem;
  cursor: pointer;
  transition:
    color var(--transition),
    border-color var(--transition),
    background var(--transition);
}

.collapse-btn:hover {
  color: var(--brand);
  border-color: var(--brand);
  background: var(--brand-soft);
}

/* ---------- 新对话 ---------- */
.new-chat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid var(--brand);
  border-radius: var(--radius);
  background: var(--brand);
  color: var(--text-on-brand);
  font-size: 0.9rem;
  font-weight: 650;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition:
    background var(--transition),
    transform var(--transition);
}

.new-chat:hover {
  background: var(--brand-hover);
}

.new-chat:active {
  transform: translateY(1px);
}

.sidenav--collapsed .new-chat {
  width: 40px;
  height: 40px;
  padding: 0;
}

.new-chat__icon {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1;
}

/* ---------- 报告 / 学习方案入口 ---------- */
.report-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--brand-soft);
  border-radius: var(--radius);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 0.88rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--transition),
    border-color var(--transition),
    color var(--transition);
}

.report-link:hover {
  border-color: var(--brand);
  color: var(--brand-active);
}

/* 面板已展开时弱化为「当前所在」态，避免与展开操作产生歧义 */
.report-link--active {
  background: transparent;
  border-color: var(--border);
  color: var(--text-secondary);
}

.report-link--active:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.sidenav--collapsed .report-link {
  width: 40px;
  height: 40px;
  padding: 0;
  justify-content: center;
}

.report-link__icon {
  font-size: 1rem;
  line-height: 1;
}

.report-link__text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- 最近会话 ---------- */
.convos {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
}

.convos__title {
  margin: 0;
  padding: 0 6px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.convos__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  scrollbar-width: thin;
}

.convo {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.86rem;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}

.convo:hover {
  background: var(--surface-muted);
  color: var(--text);
}

.convo--active {
  background: var(--brand-soft);
  color: var(--brand-active);
  font-weight: 600;
}

.convo__icon {
  flex-shrink: 0;
  font-size: 0.85em;
  opacity: 0.8;
}

.convo__text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.convos__empty {
  margin: 0;
  padding: var(--space-2) 6px;
  font-size: 0.8rem;
  color: var(--text-muted);
  line-height: 1.5;
}

/* 折叠态的历史图标按钮 */
.rail-btn {
  flex: 1;
  width: 40px;
  min-height: 40px;
  display: inline-flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: var(--space-2);
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 1.1rem;
  cursor: pointer;
}

.rail-btn:hover {
  color: var(--brand);
}

/* ---------- 底部 ---------- */
.sidenav__foot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid var(--border);
  padding-top: var(--space-3);
}

.foot-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.86rem;
  font-weight: 550;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}

.foot-link:hover {
  background: var(--surface-muted);
  color: var(--text);
}

.foot-link--active {
  background: var(--brand-soft);
  color: var(--brand);
}

.foot-link__icon {
  font-size: 0.9em;
}

/* 🔥 连续打卡角标 */
.streak-badge {
  margin-left: auto;
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--warning);
  font-variant-numeric: tabular-nums;
}

/* 折叠态底部的进度图标按钮（高度收敛，不抢占会话列表空间） */
.rail-btn--foot {
  flex: 0 0 auto;
  min-height: 36px;
  padding-top: 0;
  align-items: center;
}

.sidenav__ver {
  margin: 0;
  padding: 0 10px;
  font-size: 0.72rem;
  color: var(--text-muted);
}
</style>
