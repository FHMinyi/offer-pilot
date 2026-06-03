<script setup lang="ts">
// 历史记录页（路由 /history）
// 改用 listConversations() 列出「完整对话历史」（不再列分析 runs）。
// 挂载时拉取会话列表，分别处理 加载中 / 空 / 错误 / 正常 四种状态。
// 列表已由后端按更新时间倒序返回，前端直接渲染；整行可点击跳转到 /conversation/:id。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ConversationSummary } from '../types'
import { listConversations } from '../api/client'
import AppCard from '../components/ui/AppCard.vue'

const router = useRouter()

// 列表数据
const items = ref<ConversationSummary[]>([])
// 加载与错误状态
const loading = ref(true)
const error = ref('')

/** 拉取会话列表 */
async function load() {
  loading.value = true
  error.value = ''
  try {
    // 后端已按 updated_at 倒序排序，直接使用
    items.value = await listConversations()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载历史记录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 会话标题：空则回退为占位文案 */
function titleLabel(title: string): string {
  return title && title.trim() ? title : '未命名对话'
}

/** 将后端 ISO 时间字符串解析后按 zh-CN 本地格式展示；无法解析时原样返回 */
function formatDate(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN')
}

/**
 * 「继续」该会话：携带 ?c=<id> 进入主界面续聊。
 * 内嵌于整行链接中，需阻止事件冒泡，避免同时触发整行的「只读查看」跳转。
 */
function continueChat(id: number): void {
  void router.push({ path: '/', query: { c: id } })
}
</script>

<template>
  <section class="history">
    <!-- 页头：标题 + 新建入口 -->
    <header class="history__head">
      <div>
        <h1>历史记录</h1>
        <p class="muted">查看并回顾过往的完整对话。</p>
      </div>
      <RouterLink class="btn btn-primary" to="/">新建对话</RouterLink>
    </header>

    <!-- 加载中：骨架占位 -->
    <div v-if="loading" class="state" aria-busy="true">
      <ul class="skeleton-list">
        <li v-for="n in 3" :key="n" class="skeleton-row">
          <span class="skeleton-lines">
            <span class="skeleton skeleton--title" />
            <span class="skeleton skeleton--meta" />
          </span>
        </li>
      </ul>
    </div>

    <!-- 错误：提示 + 重试 -->
    <AppCard v-else-if="error">
      <div class="state state--center">
        <div class="state__icon state__icon--danger" aria-hidden="true">!</div>
        <h3 class="state__title">加载失败</h3>
        <p class="state__text">{{ error }}</p>
        <button class="btn btn-primary" type="button" @click="load">重试</button>
      </div>
    </AppCard>

    <!-- 空状态：引导去新建对话 / 对话分析 -->
    <AppCard v-else-if="items.length === 0">
      <div class="state state--center">
        <div class="state__icon" aria-hidden="true">💬</div>
        <h3 class="state__title">还没有对话记录</h3>
        <p class="state__text">
          开启一段新对话，上传简历并粘贴目标岗位 JD，我来帮你做求职分析。
        </p>
        <div class="state__actions">
          <RouterLink class="btn btn-primary" to="/">新建对话</RouterLink>
          <RouterLink class="btn" to="/">去对话分析</RouterLink>
        </div>
      </div>
    </AppCard>

    <!-- 正常：列表（每行可点击） -->
    <ul v-else class="list">
      <li v-for="item in items" :key="item.id">
        <RouterLink class="item" :to="`/conversation/${item.id}`">
          <!-- 主体：标题 + 元信息 -->
          <span class="item__main">
            <span class="item__title">{{ titleLabel(item.title) }}</span>
            <span class="item__meta">
              <span class="item__meta-piece">{{ item.turn_count }} 条消息</span>
              <span class="item__dot" aria-hidden="true">·</span>
              <time class="item__meta-piece" :datetime="item.updated_at">
                {{ formatDate(item.updated_at) }}
              </time>
            </span>
          </span>

          <!-- 「继续」入口：在本会话基础上续聊（→ /?c=<id>）。
               阻止冒泡与默认跳转，避免触发整行的「只读查看」。 -->
          <button
            type="button"
            class="item__continue"
            title="在本会话基础上继续对话"
            @click.stop.prevent="continueChat(item.id)"
          >
            继续
          </button>

          <!-- 右侧指示箭头 -->
          <span class="item__arrow" aria-hidden="true">›</span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

/* 页头 */
.history__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.history__head .muted {
  margin-top: var(--space-1);
}

/* ---------- 列表 ---------- */
.list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.item {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  color: var(--text);
  transition:
    border-color var(--transition),
    box-shadow var(--transition),
    transform var(--transition);
}

.item:hover {
  border-color: var(--brand);
  box-shadow: var(--shadow-md);
  color: var(--text);
}

.item:active {
  transform: translateY(1px);
}

/* 主体文本区 */
.item__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.item__title {
  font-weight: 600;
  font-size: 1.02rem;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  color: var(--text-muted);
  font-size: 0.875rem;
}

.item__dot {
  color: var(--border-strong);
}

/* 右侧箭头 */
.item__arrow {
  flex-shrink: 0;
  font-size: 1.5rem;
  line-height: 1;
  color: var(--text-muted);
  transition:
    color var(--transition),
    transform var(--transition);
}

.item:hover .item__arrow {
  color: var(--brand);
  transform: translateX(2px);
}

/* 「继续」入口：弱化的胶囊按钮，悬停高亮为品牌色 */
.item__continue {
  flex-shrink: 0;
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 0.82rem;
  font-weight: 600;
  transition:
    background var(--transition),
    border-color var(--transition),
    color var(--transition);
}

.item__continue:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

/* ---------- 通用状态块 ---------- */
.state--center {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
}

.state__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-pill);
  background: var(--surface-muted);
  font-size: 1.5rem;
  line-height: 1;
}

.state__icon--danger {
  background: var(--danger-soft);
  color: var(--danger);
  font-weight: 800;
}

.state__title {
  color: var(--text);
}

.state__text {
  max-width: 36ch;
  color: var(--text-muted);
}

.state__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: center;
}

/* ---------- 加载骨架 ---------- */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton {
  display: block;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--surface-muted) 25%,
    #eceef1 37%,
    var(--surface-muted) 63%
  );
  background-size: 400% 100%;
  animation: skeleton-shimmer 1.4s ease infinite;
}

.skeleton--title {
  width: 42%;
  height: 16px;
}

.skeleton--meta {
  width: 64%;
  height: 12px;
}

@keyframes skeleton-shimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: 0 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton {
    animation: none;
  }
}

@media (max-width: 560px) {
  .item {
    padding: var(--space-3) var(--space-4);
    gap: var(--space-3);
  }

  .item__arrow {
    display: none;
  }
}
</style>
