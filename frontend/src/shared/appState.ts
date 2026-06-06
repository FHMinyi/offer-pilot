// 轻量全局 UI 状态：左侧边栏开合 + 跨组件信号。
// 不引入 Pinia，仅用 Vue 的 reactive/ref 做一个极小的共享单例，
// 解决「侧边栏（App 外壳）」与「对话视图（ChatView）」之间的双向协同：
//   · 侧栏「新对话」要让 ChatView 重置当前对话；
//   · ChatView 自动保存会话后，要让侧栏刷新会话列表；
//   · 折叠态需在多视图间共享并持久化。

import { reactive, ref } from 'vue'
import type { ProgressSummary } from '../types'

const COLLAPSE_KEY = 'op.sidebar.collapsed'

/** 读取持久化的折叠态（SSR/隐私模式下 localStorage 可能不可用，做容错）。 */
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * 侧边栏状态：
 * - collapsed：宽屏下是否收成「窄图标栏」（持久化）。
 * - mobileOpen：窄屏下抽屉是否展开（不持久化，切换路由/点遮罩即关）。
 */
export const sidebarState = reactive({
  collapsed: readCollapsed(),
  mobileOpen: false,
})

/**
 * 是否宽屏（与 App/ChatView 的抽屉断点 960px 对齐）。
 * 窄屏下侧栏化为抽屉，应忽略「折叠成窄栏」的桌面偏好、始终展示完整侧栏，
 * 故 SideNav 用 collapsed && isWide 作为「有效折叠」。
 */
export const isWide = ref(true)
try {
  const mq = window.matchMedia('(min-width: 961px)')
  isWide.value = mq.matches
  mq.addEventListener('change', (e) => {
    isWide.value = e.matches
  })
} catch {
  /* 非浏览器环境/不支持 matchMedia：保持默认 true */
}

/** 宽屏：折叠 / 展开侧栏（持久化）。 */
export function toggleSidebarCollapsed(): void {
  sidebarState.collapsed = !sidebarState.collapsed
  try {
    localStorage.setItem(COLLAPSE_KEY, sidebarState.collapsed ? '1' : '0')
  } catch {
    /* 忽略持久化失败 */
  }
}

/** 窄屏：打开抽屉。 */
export function openMobileSidebar(): void {
  sidebarState.mobileOpen = true
}

/** 窄屏：关闭抽屉。 */
export function closeMobileSidebar(): void {
  sidebarState.mobileOpen = false
}

// —— 跨组件信号（自增计数，监听方 watch 其变化即可）——

/** 「新对话」信号：侧栏点击 +1；ChatView watch 到变化后重置当前对话。 */
export const newChatSignal = ref(0)
export function requestNewChat(): void {
  newChatSignal.value++
}

/** 「会话列表已变更」信号：ChatView 保存会话后 +1；侧栏 watch 到后重新拉取列表。 */
export const conversationsChanged = ref(0)
export function notifyConversationsChanged(): void {
  conversationsChanged.value++
}

// —— 报告面板跨组件协同（ChatView ⇄ SideNav）——
// 报告/学习方案的入口从右下角悬浮角标移到左侧边栏，统一视觉、避免与发送按钮重叠。
// ChatView 把「当前是否有报告 / 面板是否展开 / 是否已出方案」同步到 reportNav，
// 侧栏据此显示「报告 / 学习方案」入口；点击入口发 openReportSignal，
// ChatView watch 到后展开并滚动高亮报告面板。

/**
 * 报告导航状态（由 ChatView 写入，SideNav 读取）：
 * - available：当前对话是否已有最新报告（无则侧栏不显示入口）。
 * - open：报告面板是否展开（决定侧栏入口的高亮态）。
 * - hasPlan：是否已生成学习方案（决定入口图标/文案：🎓学习方案 / 📊匹配分析）。
 */
export const reportNav = reactive({
  available: false,
  open: false,
  hasPlan: false,
})

/** 「展开/定位报告面板」信号：侧栏点击 +1；ChatView watch 到后展开并滚动高亮。 */
export const openReportSignal = ref(0)
export function requestOpenReport(): void {
  openReportSignal.value++
}

// —— 进度闭环跨组件协同（里程碑一）——
// 勾选任务 / 每日打卡成功后通知进度看板与侧栏 streak 角标惰性重拉，避免各自轮询。

/** 「进度已变更」信号：勾选/打卡成功后 +1；看板、侧栏 watch 后重拉。 */
export const progressChanged = ref(0)
export function notifyProgressChanged(): void {
  progressChanged.value++
}

/**
 * 进度缓存（SideNav streak 角标与 Dashboard 共享，避免重复请求）。
 * loadedAt 为时间戳（毫秒），用于判断是否需要刷新。
 */
export const progressCache = reactive<{ value: ProgressSummary | null; loadedAt: number }>({
  value: null,
  loadedAt: 0,
})
