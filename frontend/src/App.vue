<script setup lang="ts">
// 应用外壳：左侧可折叠导航边栏 + 右侧主区路由出口。
// 取代旧的顶部品牌栏——品牌 / 新对话 / 历史记录全部移入 SideNav，
// 主区顶部不再有任何遮挡对话内容的横栏。
//
// 响应式：
//   · 宽屏（>768px）：侧栏常驻左侧，可折叠成窄图标栏。
//   · 窄屏（≤768px）：侧栏化为抽屉，由汉堡按钮唤出、点遮罩关闭；切换路由自动关闭。
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import SideNav from './components/SideNav.vue'
import {
  sidebarState,
  openMobileSidebar,
  closeMobileSidebar,
} from './shared/appState'

const route = useRoute()

// 对话主界面（路由名 'new'）：主区交由 ChatView 自行管理内部滚动，去掉外层留白。
const isChat = computed(() => route.name === 'new')

// 切换路由时收起窄屏抽屉，避免抽屉残留遮挡。
watch(
  () => route.fullPath,
  () => closeMobileSidebar(),
)
</script>

<template>
  <div class="app-shell">
    <!-- 左侧边栏：宽屏常驻 / 窄屏抽屉 -->
    <div class="app-sidebar" :class="{ 'app-sidebar--open': sidebarState.mobileOpen }">
      <SideNav />
    </div>

    <!-- 窄屏抽屉遮罩 -->
    <div
      v-if="sidebarState.mobileOpen"
      class="app-backdrop"
      aria-hidden="true"
      @click="closeMobileSidebar"
    />

    <!-- 主区 -->
    <main class="app-main" :class="{ 'app-main--chat': isChat }">
      <!-- 窄屏汉堡按钮（宽屏隐藏） -->
      <button
        type="button"
        class="app-menu"
        aria-label="打开导航菜单"
        @click="openMobileSidebar"
      >
        ☰
      </button>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg);
}

/* 侧栏定位容器：宽屏在流内；窄屏改 fixed 抽屉 */
.app-sidebar {
  flex-shrink: 0;
  height: 100%;
}

/* ---------- 主区 ---------- */
.app-main {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  scrollbar-width: thin;
}

/* 非对话路由（结果 / 历史 / 会话）：留出内边距并居中内容 */
.app-main:not(.app-main--chat) {
  padding: var(--space-5) var(--space-5) var(--space-7);
}

.app-main:not(.app-main--chat) > :not(.app-menu) {
  max-width: var(--container-max);
  margin-inline: auto;
}

/* 对话路由：full-bleed，由 ChatView 自管内部滚动与留白。
   宽屏 overflow:hidden——仅 ChatView 内部的 .chat__scroll 滚动，避免与主区双滚动条。
   窄屏（≤960px，ChatView 改为纵向堆叠 height:auto）下方媒体查询会放开为页面滚动。 */
.app-main--chat {
  padding: 0;
  overflow: hidden;
}

/* 汉堡按钮：宽屏隐藏 */
.app-menu {
  display: none;
}

.app-backdrop {
  display: none;
}

/* ---------- 窄屏抽屉 ----------
   断点与 ChatView 的两栏→纵向堆叠断点（960px）对齐：≤960 时侧栏收为抽屉，
   把整屏宽度让给纵向堆叠的对话，避免「侧栏常驻 + 对话已堆叠」的中间尴尬态。 */
@media (max-width: 960px) {
  .app-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: var(--shadow-md);
  }

  /* 窄屏对话：放开为页面滚动（ChatView 此时 height:auto，内容随页面滚动） */
  .app-main--chat {
    overflow-y: auto;
  }

  .app-sidebar--open {
    transform: translateX(0);
  }

  .app-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 40;
    background: rgba(15, 23, 42, 0.42);
  }

  .app-menu {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    position: absolute;
    top: 10px;
    left: 10px;
    z-index: 10;
    width: 38px;
    height: 38px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text-secondary);
    font-size: 1.1rem;
    box-shadow: var(--shadow-sm);
  }

  .app-menu:hover {
    color: var(--brand);
    border-color: var(--brand);
  }

  /* 非对话页：给汉堡按钮让出顶部空间 */
  .app-main:not(.app-main--chat) {
    padding-top: calc(var(--space-5) + 44px);
  }

  /* 对话页：让出顶部空间，避免汉堡按钮压住首条消息 */
  .app-main--chat {
    padding-top: 46px;
  }
}
</style>
