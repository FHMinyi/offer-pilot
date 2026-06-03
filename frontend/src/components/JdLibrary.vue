<script setup lang="ts">
// JD 库（自包含模态）
// ----------------------------------------------------------------------
// 列出已保存的测试 JD（标题 + 内容预览 + 更新时间），支持：
//   · 新建（标题 + 多行内容）
//   · 就地编辑某条
//   · 删除（带确认）
//   · 勾选多条 / 单条「加入分析」，底部「添加所选到分析」一次性 emit
// 数据自取：打开时调用 listSavedJds 拉取；增删改后本地同步并保持 updated_at 倒序。
// 视觉沿用 main.css 设计令牌与 .btn/.field 等通用类，纯 CSS scoped，无外部依赖。

import { computed, reactive, ref, watch } from 'vue'
import {
  createSavedJd,
  deleteSavedJd,
  listSavedJds,
  updateSavedJd,
} from '../api/client'
import type { SavedJd } from '../types'

const props = defineProps<{
  /** 是否打开模态 */
  open: boolean
}>()

const emit = defineEmits<{
  /** 关闭模态（遮罩点击 / 关闭按钮 / Esc / 完成添加后） */
  (e: 'close'): void
  /** 把选中的 JD 内容列表加入本次分析 */
  (e: 'use', payload: string[]): void
}>()

// ---------- 列表与请求状态 ----------
const items = ref<SavedJd[]>([])
const loading = ref(false)
const error = ref('') // 列表级错误
const actionError = ref('') // 增删改级错误（不阻塞列表展示）

// 勾选集合：记录被选中的 JD id
const selected = reactive(new Set<number>())

// ---------- 新建表单 ----------
const creating = ref(false) // 是否展开新建表单
const createForm = reactive({ title: '', content: '' })
const createSaving = ref(false)

// ---------- 就地编辑 ----------
const editingId = ref<number | null>(null)
const editForm = reactive({ title: '', content: '' })
const editSaving = ref(false)

// ---------- 删除确认 ----------
const confirmingId = ref<number | null>(null) // 正在等待二次确认删除的条目
const deletingId = ref<number | null>(null) // 正在请求删除中的条目

// 选中数量（用于底部按钮文案与禁用态）
const selectedCount = computed(() => selected.size)

/** 把 ISO 时间字符串格式化为本地可读时间 */
function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN')
}

/** 拉取列表（打开时调用） */
async function fetchList(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    items.value = await listSavedJds()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载 JD 库失败'
  } finally {
    loading.value = false
  }
}

/** 重置所有瞬态交互态（关闭或重新打开时） */
function resetTransient(): void {
  selected.clear()
  creating.value = false
  createForm.title = ''
  createForm.content = ''
  createSaving.value = false
  editingId.value = null
  editForm.title = ''
  editForm.content = ''
  editSaving.value = false
  confirmingId.value = null
  deletingId.value = null
  actionError.value = ''
}

// 打开时拉取并复位；关闭时复位瞬态
watch(
  () => props.open,
  (open) => {
    if (open) {
      resetTransient()
      void fetchList()
    } else {
      resetTransient()
    }
  },
  { immediate: true },
)

// ---------- 勾选 ----------
function toggleSelect(id: number): void {
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
}

// ---------- 新建 ----------
function openCreate(): void {
  creating.value = true
  createForm.title = ''
  createForm.content = ''
  actionError.value = ''
}

function cancelCreate(): void {
  creating.value = false
  createForm.title = ''
  createForm.content = ''
}

async function submitCreate(): Promise<void> {
  const title = createForm.title.trim()
  const content = createForm.content.trim()
  if (!title || !content) {
    actionError.value = '标题与内容均不能为空'
    return
  }
  createSaving.value = true
  actionError.value = ''
  try {
    const created = await createSavedJd({ title, content })
    // 新建即最新：置顶
    items.value = [created, ...items.value]
    cancelCreate()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    createSaving.value = false
  }
}

// ---------- 编辑 ----------
function startEdit(item: SavedJd): void {
  editingId.value = item.id
  editForm.title = item.title
  editForm.content = item.content
  actionError.value = ''
  // 进入编辑时收起删除确认，避免状态叠加
  confirmingId.value = null
}

function cancelEdit(): void {
  editingId.value = null
  editForm.title = ''
  editForm.content = ''
}

async function submitEdit(id: number): Promise<void> {
  const title = editForm.title.trim()
  const content = editForm.content.trim()
  if (!title || !content) {
    actionError.value = '标题与内容均不能为空'
    return
  }
  editSaving.value = true
  actionError.value = ''
  try {
    const updated = await updateSavedJd(id, { title, content })
    // 更新后置顶（updated_at 最新），并去掉原位置
    items.value = [updated, ...items.value.filter((it) => it.id !== id)]
    cancelEdit()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '更新失败'
  } finally {
    editSaving.value = false
  }
}

// ---------- 删除 ----------
function askDelete(id: number): void {
  confirmingId.value = id
  actionError.value = ''
}

function cancelDelete(): void {
  confirmingId.value = null
}

async function confirmDelete(id: number): Promise<void> {
  deletingId.value = id
  actionError.value = ''
  try {
    await deleteSavedJd(id)
    items.value = items.value.filter((it) => it.id !== id)
    selected.delete(id)
    confirmingId.value = null
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    deletingId.value = null
  }
}

// ---------- 加入分析 ----------
/** 单条直接加入并关闭 */
function useOne(item: SavedJd): void {
  emit('use', [item.content])
  emit('close')
}

/** 添加所选到分析（按当前列表顺序收集 content） */
function useSelected(): void {
  if (selected.size === 0) return
  const contents = items.value
    .filter((it) => selected.has(it.id))
    .map((it) => it.content)
  emit('use', contents)
  emit('close')
}

// ---------- 关闭 ----------
function close(): void {
  emit('close')
}

/** 仅当点击到遮罩本身（而非内容区）时关闭 */
function onOverlayClick(e: MouseEvent): void {
  if (e.target === e.currentTarget) close()
}
</script>

<template>
  <Transition name="jdlib-fade">
    <div
      v-if="open"
      class="jdlib__overlay"
      role="dialog"
      aria-modal="true"
      aria-label="JD 库"
      @click="onOverlayClick"
      @keydown.esc="close"
    >
      <div class="jdlib__panel" tabindex="-1">
        <!-- 头部 -->
        <header class="jdlib__head">
          <div class="jdlib__heading">
            <h2 class="jdlib__title">JD 库</h2>
            <p class="jdlib__subtitle">复用已保存的岗位 JD，勾选后加入本次分析</p>
          </div>
          <div class="jdlib__head-actions">
            <button type="button" class="btn btn-primary" @click="openCreate">
              + 新建 JD
            </button>
            <button
              type="button"
              class="jdlib__close"
              aria-label="关闭"
              @click="close"
            >
              ✕
            </button>
          </div>
        </header>

        <!-- 主体（可滚动） -->
        <div class="jdlib__body">
          <!-- 新建表单 -->
          <form v-if="creating" class="jdlib__form" @submit.prevent="submitCreate">
            <div class="jdlib__form-title">新建 JD</div>
            <input
              v-model="createForm.title"
              class="field"
              type="text"
              placeholder="标题，例如：后端工程师 · 某公司"
              :disabled="createSaving"
            />
            <textarea
              v-model="createForm.content"
              class="field jdlib__textarea"
              rows="6"
              placeholder="粘贴岗位 JD 全文…"
              :disabled="createSaving"
            ></textarea>
            <div class="jdlib__form-actions">
              <button
                type="button"
                class="btn"
                :disabled="createSaving"
                @click="cancelCreate"
              >
                取消
              </button>
              <button
                type="submit"
                class="btn btn-primary"
                :disabled="createSaving"
              >
                {{ createSaving ? '保存中…' : '保存到库' }}
              </button>
            </div>
          </form>

          <!-- 增删改级错误（轻量提示，不阻塞列表） -->
          <p v-if="actionError" class="jdlib__action-error" role="alert">
            {{ actionError }}
          </p>

          <!-- 加载中 -->
          <div v-if="loading" class="jdlib__state">
            <span class="jdlib__spinner" aria-hidden="true"></span>
            <span>正在加载 JD 库…</span>
          </div>

          <!-- 列表级错误 -->
          <div v-else-if="error" class="jdlib__state jdlib__state--error">
            <p>{{ error }}</p>
            <button type="button" class="btn" @click="fetchList">重试</button>
          </div>

          <!-- 空状态 -->
          <div
            v-else-if="items.length === 0 && !creating"
            class="jdlib__state jdlib__state--empty"
          >
            <p>JD 库还是空的。</p>
            <button type="button" class="btn btn-primary" @click="openCreate">
              新建第一条 JD
            </button>
          </div>

          <!-- 列表 -->
          <ul v-else class="jdlib__list">
            <li
              v-for="item in items"
              :key="item.id"
              class="jdlib__item"
              :class="{ 'jdlib__item--selected': selected.has(item.id) }"
            >
              <!-- 编辑态 -->
              <form
                v-if="editingId === item.id"
                class="jdlib__form jdlib__form--inline"
                @submit.prevent="submitEdit(item.id)"
              >
                <input
                  v-model="editForm.title"
                  class="field"
                  type="text"
                  placeholder="标题"
                  :disabled="editSaving"
                />
                <textarea
                  v-model="editForm.content"
                  class="field jdlib__textarea"
                  rows="6"
                  placeholder="JD 内容"
                  :disabled="editSaving"
                ></textarea>
                <div class="jdlib__form-actions">
                  <button
                    type="button"
                    class="btn"
                    :disabled="editSaving"
                    @click="cancelEdit"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    class="btn btn-primary"
                    :disabled="editSaving"
                  >
                    {{ editSaving ? '保存中…' : '保存修改' }}
                  </button>
                </div>
              </form>

              <!-- 展示态 -->
              <template v-else>
                <label class="jdlib__check">
                  <input
                    type="checkbox"
                    :checked="selected.has(item.id)"
                    @change="toggleSelect(item.id)"
                  />
                </label>
                <div class="jdlib__main">
                  <div class="jdlib__item-head">
                    <h3 class="jdlib__item-title">{{ item.title }}</h3>
                    <time class="jdlib__time">{{ formatTime(item.updated_at) }}</time>
                  </div>
                  <p class="jdlib__preview">{{ item.content }}</p>

                  <!-- 删除确认条 -->
                  <div v-if="confirmingId === item.id" class="jdlib__confirm">
                    <span>确认删除这条 JD？</span>
                    <button
                      type="button"
                      class="btn btn-ghost jdlib__danger"
                      :disabled="deletingId === item.id"
                      @click="confirmDelete(item.id)"
                    >
                      {{ deletingId === item.id ? '删除中…' : '确认删除' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-ghost"
                      :disabled="deletingId === item.id"
                      @click="cancelDelete"
                    >
                      取消
                    </button>
                  </div>

                  <!-- 行操作 -->
                  <div v-else class="jdlib__item-actions">
                    <button
                      type="button"
                      class="btn btn-primary jdlib__add"
                      @click="useOne(item)"
                    >
                      加入分析
                    </button>
                    <button type="button" class="btn btn-ghost" @click="startEdit(item)">
                      编辑
                    </button>
                    <button
                      type="button"
                      class="btn btn-ghost jdlib__danger"
                      @click="askDelete(item.id)"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </template>
            </li>
          </ul>
        </div>

        <!-- 底部：批量加入 -->
        <footer class="jdlib__foot">
          <span class="muted">
            已选 {{ selectedCount }} 条
          </span>
          <div class="jdlib__foot-actions">
            <button type="button" class="btn" @click="close">取消</button>
            <button
              type="button"
              class="btn btn-primary"
              :disabled="selectedCount === 0"
              @click="useSelected"
            >
              添加所选到分析
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* 遮罩：覆盖全屏、居中面板 */
.jdlib__overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  background: rgba(15, 23, 42, 0.45);
}

/* 面板：白底卡片，限定最大高度内部滚动 */
.jdlib__panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 720px;
  max-height: min(86vh, 760px);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

/* ---------- 头部 ---------- */
.jdlib__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}

.jdlib__title {
  font-size: 1.15rem;
  font-weight: 650;
  color: var(--text);
}

.jdlib__subtitle {
  margin-top: 2px;
  font-size: 0.875rem;
  color: var(--text-muted);
}

.jdlib__head-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.jdlib__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font-size: 1rem;
  line-height: 1;
  transition:
    background var(--transition),
    color var(--transition);
}

.jdlib__close:hover {
  background: var(--surface-muted);
  color: var(--text);
}

/* ---------- 主体 ---------- */
.jdlib__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ---------- 表单（新建 / 编辑共用） ---------- */
.jdlib__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-muted);
}

.jdlib__form--inline {
  background: var(--brand-soft);
  border-color: #c7d8ff;
}

.jdlib__form-title {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.jdlib__textarea {
  min-height: 120px;
  line-height: 1.55;
  font-family: var(--font-sans);
}

.jdlib__form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

/* ---------- 状态块（加载/错误/空） ---------- */
.jdlib__state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-7) var(--space-4);
  color: var(--text-muted);
  text-align: center;
}

.jdlib__state--error p {
  color: var(--danger);
}

.jdlib__spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: jdlib-spin 0.7s linear infinite;
}

@keyframes jdlib-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 增删改级错误条 */
.jdlib__action-error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid #f6c9c9;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 0.875rem;
}

/* ---------- 列表 ---------- */
.jdlib__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.jdlib__item {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  transition:
    border-color var(--transition),
    box-shadow var(--transition);
}

.jdlib__item--selected {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.jdlib__check {
  flex-shrink: 0;
  padding-top: 2px;
}

.jdlib__check input {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--brand);
}

.jdlib__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.jdlib__item-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.jdlib__item-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jdlib__time {
  flex-shrink: 0;
  font-size: 0.8rem;
  color: var(--text-muted);
}

/* 内容预览：最多三行省略 */
.jdlib__preview {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
  line-height: 1.55;
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.jdlib__item-actions,
.jdlib__confirm {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-top: var(--space-1);
}

.jdlib__confirm {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

/* 行内紧凑按钮 */
.jdlib__item-actions .btn,
.jdlib__confirm .btn {
  padding: 5px 12px;
  font-size: 0.85rem;
}

.jdlib__add {
  font-weight: 550;
}

/* 危险操作文字色 */
.jdlib__danger {
  color: var(--danger);
}

.jdlib__danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: transparent;
}

/* ---------- 底部 ---------- */
.jdlib__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.jdlib__foot-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ---------- 过渡 ---------- */
.jdlib-fade-enter-active,
.jdlib-fade-leave-active {
  transition: opacity var(--transition);
}

.jdlib-fade-enter-from,
.jdlib-fade-leave-to {
  opacity: 0;
}

/* ---------- 窄屏 ---------- */
@media (max-width: 640px) {
  .jdlib__overlay {
    padding: 0;
    align-items: stretch;
  }

  .jdlib__panel {
    max-width: none;
    max-height: 100vh;
    height: 100vh;
    border-radius: 0;
    border: 0;
  }

  .jdlib__head-actions {
    gap: var(--space-2);
  }
}
</style>
