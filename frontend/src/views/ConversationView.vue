<script setup lang="ts">
// 会话回看页（路由 /conversation/:id）——【只读】
//
// 职责概览：
//   · 挂载时按 id 拉取整段会话记录（getConversation），处理 加载中 / 错误 / 正常。
//   · 以与 ChatView 消息区一致的视觉，回放完整对话 turns，但不带任何输入框，
//     纯粹用于历史回看。
//   · 助手回合严格按持久化的有序 blocks 顺序渲染：
//       text / reasoning  → <MarkdownText>（reasoning 作为「💭 思考过程」弱化区，
//                            可折叠，默认折叠）
//       tool              → 一行小字活动（含 label 与 ok 的 ✓/×）
//       report            → <AnalysisReport> 全宽渲染（对空段落优雅隐藏，
//                            可承载「两步分析」中先到的部分报告）
//   · 顶部：标题 + 时间 + 「← 返回历史」 + 「＋ 新对话」入口。
//
// 渲染模型复用 ChatView 的「有序 blocks」思路，但本文件自包含（不依赖其内部状态）。
import { onMounted, reactive, ref } from 'vue'
import type { ConversationDetail, PersistedTurn } from '../types'
import { getConversation } from '../api/client'
import AnalysisReport from '../components/AnalysisReport.vue'
import MarkdownText from '../components/MarkdownText.vue'
import AppCard from '../components/ui/AppCard.vue'

const props = defineProps<{
  /** 路由参数 id（字符串），渲染前转 Number 调接口 */
  id: string
}>()

// ---------- 状态 ----------
const detail = ref<ConversationDetail | null>(null)
const loading = ref(true)
const error = ref('')

// 各助手回合内 reasoning 块的展开态：key = `${turnIndex}:${blockIndex}`，默认折叠。
const reasoningOpen = reactive<Record<string, boolean>>({})

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
    detail.value = await getConversation(numericId)
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

/** 依据工具名给一个图标；默认放大镜（与 ChatView 一致） */
function toolIcon(name: string): string {
  if (name === 'web_search') return '🔍'
  if (name === 'run_analysis' || name === 'analysis' || name === 'analyze') return '📊'
  return '🛠'
}

/** 切换某个思考块的展开/收起 */
function toggleReasoning(turnIndex: number, blockIndex: number): void {
  const key = `${turnIndex}:${blockIndex}`
  reasoningOpen[key] = !reasoningOpen[key]
}

/** 某个思考块是否展开（默认折叠） */
function isReasoningOpen(turnIndex: number, blockIndex: number): boolean {
  return !!reasoningOpen[`${turnIndex}:${blockIndex}`]
}

/** 该助手回合是否需要渲染气泡：含任意非 report 块、或有错误 / 无思考提示 */
function hasBubble(turn: Extract<PersistedTurn, { role: 'assistant' }>): boolean {
  if (turn.error || turn.noThinking) return true
  return turn.blocks.some((b) => b.kind !== 'report')
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
      <template v-for="(turn, ti) in detail.turns" :key="ti">
        <!-- 用户气泡（右）：纯文本 -->
        <div v-if="turn.role === 'user'" class="msg msg--user">
          <div class="bubble bubble--user">{{ turn.text }}</div>
        </div>

        <!-- 助手气泡（左）：按 blocks 顺序渲染 -->
        <div v-else class="msg msg--assistant">
          <div class="avatar avatar--assistant" aria-hidden="true">OP</div>
          <div class="msg__assistant-body">
            <!-- 气泡：思考 / 文本 / 工具，按顺序交错；报告在气泡外全宽渲染 -->
            <div v-if="hasBubble(turn)" class="bubble bubble--assistant">
              <template v-for="(block, bi) in turn.blocks" :key="bi">
                <!-- 思考过程：可折叠、弱化、markdown，默认折叠 -->
                <section
                  v-if="block.kind === 'reasoning'"
                  class="reasoning"
                  :class="{ 'reasoning--open': isReasoningOpen(ti, bi) }"
                >
                  <button
                    type="button"
                    class="reasoning__head"
                    :aria-expanded="isReasoningOpen(ti, bi)"
                    @click="toggleReasoning(ti, bi)"
                  >
                    <span class="reasoning__icon" aria-hidden="true">💭</span>
                    <span class="reasoning__title">思考过程</span>
                    <span
                      class="reasoning__caret"
                      :class="{ open: isReasoningOpen(ti, bi) }"
                      aria-hidden="true"
                    >▸</span>
                  </button>
                  <div v-show="isReasoningOpen(ti, bi)" class="reasoning__body">
                    <MarkdownText :text="block.text" />
                  </div>
                </section>

                <!-- 普通回复：markdown -->
                <MarkdownText
                  v-else-if="block.kind === 'text'"
                  class="bubble__md"
                  :text="block.text"
                />

                <!-- 工具活动：标题行（含 label 与 ok 的 ✓/×）+ 过程日志列表（只读回看） -->
                <div
                  v-else-if="block.kind === 'tool'"
                  class="tool"
                  :class="{
                    'tool--done': block.ok === true,
                    'tool--fail': block.ok === false,
                    'tool--running': block.ok === undefined,
                  }"
                >
                  <div class="tool__head">
                    <span class="tool__icon" aria-hidden="true">
                      {{ toolIcon(block.name) }}
                    </span>
                    <span class="tool__label">{{ block.label }}</span>
                    <span class="tool__state">
                      <span v-if="block.ok === true" class="tool__check">✓</span>
                      <span v-else-if="block.ok === false" class="tool__cross">✕</span>
                    </span>
                  </div>
                  <!-- 过程日志：每行小字、弱化，缩进于标题行之下（只读，无 spinner） -->
                  <ul v-if="block.steps && block.steps.length" class="tool__steps">
                    <li v-for="(step, si) in block.steps" :key="si" class="tool__step">
                      <span class="tool__step-dot" aria-hidden="true">·</span>
                      <span class="tool__step-text">{{ step }}</span>
                    </li>
                  </ul>
                </div>
              </template>

              <!-- 错误条（只读，无重试） -->
              <div v-if="turn.error" class="err" role="alert">
                <span class="err__text">{{ turn.error }}</span>
              </div>

              <!-- 无思考提示：弱化小字 -->
              <p v-if="turn.noThinking" class="no-thinking">
                （当前模型本轮未输出思考过程）
              </p>
            </div>

            <!-- 报告卡：按 blocks 顺序、气泡外全宽渲染（可有多份，与文本交错） -->
            <template v-for="(block, bi) in turn.blocks" :key="`r-${bi}`">
              <div v-if="block.kind === 'report'" class="report-slot">
                <AnalysisReport
                  :result="block.result"
                  :run-id="block.analysis_run_id"
                  :from-conversation-id="Number(id)"
                />
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
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

/* ---------- 气泡 ---------- */
.bubble {
  position: relative;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  line-height: 1.65;
  font-size: 0.95rem;
  word-break: break-word;
  box-shadow: var(--shadow-sm);
}

.bubble--user {
  background: var(--brand);
  color: var(--text-on-brand);
  border-bottom-right-radius: var(--radius-sm);
  max-width: min(78%, 640px);
  white-space: pre-wrap; /* 保留用户输入的换行 */
}

.bubble--assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-bottom-left-radius: var(--radius-sm);
  max-width: min(88%, 760px);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bubble__md {
  color: var(--text);
}

/* ---------- 思考过程（可折叠、弱化） ---------- */
.reasoning {
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-muted);
}

.reasoning__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.reasoning__head:hover {
  color: var(--text-secondary);
}

.reasoning__icon {
  font-size: 0.9em;
}

.reasoning__title {
  flex: 1;
}

.reasoning__caret {
  flex-shrink: 0;
  font-size: 0.7rem;
  transition: transform var(--transition);
}

.reasoning__caret.open {
  transform: rotate(90deg);
}

.reasoning__body {
  padding: 0 10px 8px;
  color: var(--text-muted);
  font-size: 0.86rem;
}

.reasoning__body :deep(.md) {
  font-size: 0.86rem;
  color: var(--text-muted);
}

.reasoning__body :deep(.md) strong,
.reasoning__body :deep(.md) h1,
.reasoning__body :deep(.md) h2,
.reasoning__body :deep(.md) h3 {
  color: var(--text-secondary);
}

/* ---------- 工具活动（标题行 + 过程日志列表） ---------- */
.tool {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 10px;
  border-radius: var(--radius);
  background: var(--surface-muted);
  border: 1px solid var(--border);
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.tool--running {
  border-color: var(--border-strong);
}

.tool--done {
  background: var(--success-soft);
  border-color: #bfe6cb;
}

.tool--fail {
  background: var(--danger-soft);
  border-color: #f6c9c9;
}

/* 标题行：图标 + 结果摘要 + 完成态标记 */
.tool__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.tool__icon {
  flex-shrink: 0;
}

.tool__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool__state {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
}

/* 过程日志列表：缩进于图标之下，每行小字、弱化 */
.tool__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  padding-left: calc(1em + var(--space-2));
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tool__step {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.5;
}

.tool__step-dot {
  flex-shrink: 0;
  color: var(--text-muted);
  opacity: 0.7;
}

.tool__step-text {
  min-width: 0;
  word-break: break-word;
}

.tool__check {
  color: var(--success);
  font-weight: 700;
}

.tool__cross {
  color: var(--danger);
  font-weight: 700;
}

/* ---------- 错误条（只读） ---------- */
.err {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  background: var(--danger-soft);
  border: 1px solid #f6c9c9;
}

.err__text {
  flex: 1;
  min-width: 0;
  font-size: 0.88rem;
  color: var(--danger);
}

/* ---------- 无思考提示（很弱化的小字） ---------- */
.no-thinking {
  margin: 0;
  font-size: 0.76rem;
  color: var(--text-muted);
  opacity: 0.7;
  font-style: italic;
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
  animation: conv-spin 0.7s linear infinite;
}

@keyframes conv-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation: none;
  }
}

/* ---------- 响应式 ---------- */
@media (max-width: 640px) {
  .bubble--user {
    max-width: 86%;
  }

  .bubble--assistant {
    max-width: 100%;
  }
}
</style>
