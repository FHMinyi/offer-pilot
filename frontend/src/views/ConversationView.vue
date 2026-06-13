<script setup lang="ts">
// 会话回看页（路由 /conversation/:id）——【只读】
//
// 职责概览：
//   · 挂载时按 id 拉取整段会话记录（getConversation），处理 加载中 / 错误 / 正常。
//   · 以与 ChatView 消息区一致的视觉，回放完整对话 turns，但不带任何输入框，
//     纯粹用于历史回看。
//   · 助手回合的气泡渲染（思考 / 文本 / 工具 / 搜索结果 / 错误条 / usage 小字）
//     复用共享渲染器 components/chat/AssistantBlocks.vue（live=false 无动效、
//     readonly 不渲染重试按钮）；报告块经 #report 插槽以 <AnalysisReport>
//     全宽渲染（可承载「两步分析」中先到的部分报告）。
//   · 持久化 PersistedTurn[] 先经 deserializeTurns 转为运行时 ChatTurn[]，
//     并以 reactive 包装，使折叠交互（思考过程 / 搜索结果展开收起）在回放可用。
//   · 顶部：标题 + 时间 + 「← 返回历史」 + 「继续对话」 + 「＋ 新对话」入口。
import { onMounted, reactive, ref } from 'vue'
import type { ConversationDetail } from '../types'
import { getConversation } from '../api/client'
import type { ChatTurn } from '../shared/chatModel'
import { attachLabel, deserializeTurns } from '../shared/chatModel'
import AnalysisReport from '../components/AnalysisReport.vue'
import AssistantBlocks from '../components/chat/AssistantBlocks.vue'
import AppCard from '../components/ui/AppCard.vue'

const props = defineProps<{
  /** 路由参数 id（字符串），渲染前转 Number 调接口 */
  id: string
}>()

// ---------- 状态 ----------
const detail = ref<ConversationDetail | null>(null)
const loading = ref(true)
const error = ref('')

// 回放用运行时回合：load 成功后由持久化 PersistedTurn[] 反序列化而来。
// deserializeTurns 返回普通对象数组，这里显式以 reactive 包装后存入，
// 使 AssistantBlocks 对折叠态（reasoningOpen / resultsOpen）的直接改写可响应。
const turns = ref<ChatTurn[]>([])

/** 拉取会话详情 */
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  const numericId = Number(props.id)
  if (!Number.isFinite(numericId)) {
    loading.value = false
    error.value = '无效的会话编号'
    return
  }
  try {
    const d = await getConversation(numericId)
    detail.value = d
    turns.value = reactive(deserializeTurns(d.turns))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载会话失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---------- 展示辅助 ----------

/** 标题：空则回退占位文案 */
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
</script>

<template>
  <section class="conv">
    <!-- 页头：标题 + 时间 + 返回 / 新对话 -->
    <header class="conv__head">
      <div class="conv__head-main">
        <h1 class="conv__title">
          {{ detail ? titleLabel(detail.title) : '对话回看' }}
        </h1>
        <p v-if="detail" class="muted conv__time">
          更新于 {{ formatDate(detail.updated_at) }}
        </p>
      </div>
      <div class="conv__head-actions">
        <RouterLink class="btn" to="/history">← 返回历史</RouterLink>
        <!-- 继续对话：携带 ?c=<id> 进入主界面，在本会话基础上续聊 -->
        <RouterLink
          class="btn btn-primary"
          :to="{ path: '/', query: { c: id } }"
        >
          继续对话
        </RouterLink>
        <RouterLink class="btn" to="/">＋ 新对话</RouterLink>
      </div>
    </header>

    <!-- 加载中：占位 -->
    <div v-if="loading" class="state state--center" aria-busy="true">
      <span class="spinner" aria-hidden="true" />
      <p class="state__text">正在加载会话…</p>
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

    <!-- 空会话：无任何回合 -->
    <AppCard v-else-if="!detail || detail.turns.length === 0">
      <div class="state state--center">
        <div class="state__icon" aria-hidden="true">💬</div>
        <h3 class="state__title">这是一段空对话</h3>
        <p class="state__text">该会话暂无可回看的消息。</p>
        <RouterLink class="btn btn-primary" to="/">去新建对话</RouterLink>
      </div>
    </AppCard>

    <!-- 正常：只读回放完整对话 -->
    <div v-else class="thread">
      <template v-for="(turn, ti) in turns" :key="ti">
        <!-- 用户气泡（右）：纯文本 + 发送时刻 -->
        <div v-if="turn.role === 'user'" class="msg msg--user">
          <div class="msg__user-wrap">
            <div class="bubble bubble--user">{{ turn.text }}</div>
            <span
              v-if="turn.attachedResume || (turn.attachedJds && turn.attachedJds.length)"
              class="msg-attach"
              >{{ attachLabel(turn.attachedResume, turn.attachedJds) }}</span
            >
            <time v-if="turn.time" class="msg-time">{{ turn.time }}</time>
          </div>
        </div>

        <!-- 助手消息（左）：气泡内部（blocks / 错误条 / 无思考提示 / usage 小字）
             由共享渲染器 AssistantBlocks 负责（live=false 无任何流式动效、
             readonly 不渲染重试按钮）；报告块经 #report 插槽以完整
             <AnalysisReport> 在气泡外全宽渲染（可有多份，与文本交错） -->
        <div v-else class="msg msg--assistant">
          <div class="avatar avatar--assistant" aria-hidden="true">OP</div>
          <div class="msg__assistant-body">
            <AssistantBlocks
              :turn="turn"
              :live="false"
              readonly
              :retry-disabled="true"
            >
              <template #report="{ block }">
                <div class="report-slot">
                  <AnalysisReport
                    :result="block.result"
                    :run-id="block.analysis_run_id"
                    :from-conversation-id="Number(id)"
                  />
                </div>
              </template>
            </AssistantBlocks>
            <time v-if="turn.time" class="msg-time">{{ turn.time }}</time>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
/* 气泡内部各段（reasoning / tool / search / err / no-thinking / usage-line）
   已随共享渲染器迁入 components/chat/AssistantBlocks.vue（scoped）；
   .bubble 基础类与 op-* 动效 keyframes 在 styles/main.css 全局。
   本文件只保留页头 / 消息行布局 / 头像 / 三态 / 报告插槽等视图私有样式。 */

.conv {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

/* ---------- 页头 ---------- */
.conv__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.conv__head-main {
  min-width: 0;
}

.conv__title {
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv__time {
  margin-top: var(--space-1);
}

.conv__head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ---------- 对话线程 ---------- */
.thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

/* ---------- 消息行 ---------- */
.msg {
  display: flex;
  gap: var(--space-3);
  max-width: 100%;
}

.msg--user {
  justify-content: flex-end;
}

/* 用户消息：气泡 + 发送时刻小字，右对齐纵向堆叠 */
.msg__user-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  min-width: 0;
}

/* 时间戳小字（用户=发送、助手=回复完成） */
.msg-time {
  font-size: 0.72rem;
  color: var(--text-muted);
  opacity: 0.75;
  user-select: none;
}

/* 素材附加紧凑标记（如「📎 已附简历 · JD ×2」）；不展示正文 */
.msg-attach {
  font-size: 0.72rem;
  color: var(--text-muted);
  opacity: 0.85;
  user-select: none;
}

.msg--assistant {
  justify-content: flex-start;
  align-items: flex-start;
}

/* 助手主体：纵向堆叠气泡与报告卡，占据剩余宽度以便报告全宽 */
.msg__assistant-body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 头像 */
.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.02em;
  margin-top: 2px;
}

.avatar--assistant {
  background: var(--brand);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-sm);
}

/* ---------- 报告卡插槽（全宽） ---------- */
.report-slot {
  width: 100%;
}

/* ---------- 状态块 ---------- */
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

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  /* 引用 main.css 的全局 op-spin（scoped keyframes 会被加 hash，故不本地定义） */
  animation: op-spin 0.7s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation: none;
  }
}
</style>
