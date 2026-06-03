<script setup lang="ts">
// Markdown 文本渲染组件
// 将传入的 markdown 文本解析为 HTML，经 DOMPurify 清洗后安全地 v-html 渲染。
// 用于聊天气泡内的助手回复、模型思考过程等需要富文本排版的场景。
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  /** 待渲染的 markdown 原文 */
  text: string
}>()

// marked 全局配置：
// gfm    启用 GitHub 风格 markdown（表格、删除线、任务列表等）
// breaks 单个换行也渲染为 <br>，贴合聊天里“按行书写”的习惯
marked.setOptions({ gfm: true, breaks: true })

// 让所有 <a> 在新标签页打开，并补上安全的 rel 属性，避免 reverse tabnabbing。
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.nodeName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// 解析 + 清洗。marked.parse 在未启用异步选项时返回同步字符串，这里显式断言为 string。
const html = computed<string>(() => {
  const raw = props.text ?? ''
  const parsed = marked.parse(raw) as string
  return DOMPurify.sanitize(parsed, { ADD_ATTR: ['target'] })
})
</script>

<template>
  <!-- 渲染结果已经过 DOMPurify 清洗，可安全使用 v-html -->
  <div class="md" v-html="html" />
</template>

<style scoped>
/* 整体：字号/行高贴合聊天气泡，去除首尾多余留白 */
.md {
  font-size: 0.94rem;
  line-height: 1.65;
  color: var(--text);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.md :deep(> :first-child) {
  margin-top: 0;
}

.md :deep(> :last-child) {
  margin-bottom: 0;
}

/* 标题层级：在气泡内整体收敛，避免过大 */
.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4),
.md :deep(h5),
.md :deep(h6) {
  margin: 1em 0 0.5em;
  font-weight: 650;
  line-height: 1.35;
  color: var(--text);
}

.md :deep(h1) {
  font-size: 1.25rem;
}

.md :deep(h2) {
  font-size: 1.12rem;
}

.md :deep(h3) {
  font-size: 1.02rem;
}

.md :deep(h4) {
  font-size: 0.96rem;
}

.md :deep(h5),
.md :deep(h6) {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

/* 段落 */
.md :deep(p) {
  margin: 0.5em 0;
  color: inherit;
}

/* 列表：恢复默认项目符号（全局 reset 去除了 list-style） */
.md :deep(ul),
.md :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.4em;
}

.md :deep(ul) {
  list-style: disc;
}

.md :deep(ol) {
  list-style: decimal;
}

.md :deep(li) {
  margin: 0.2em 0;
}

.md :deep(li > ul),
.md :deep(li > ol) {
  margin: 0.2em 0;
}

/* 任务列表（GFM）：去掉多余缩进与符号 */
.md :deep(li.task-list-item) {
  list-style: none;
  margin-left: -1.2em;
}

.md :deep(li.task-list-item input) {
  margin-right: 0.4em;
}

/* 强调 */
.md :deep(strong) {
  font-weight: 650;
  color: var(--text);
}

.md :deep(em) {
  font-style: italic;
}

.md :deep(del) {
  color: var(--text-muted);
}

/* 行内代码：浅灰底、圆角、等宽 */
.md :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.86em;
  background: var(--surface-muted);
  padding: 0.12em 0.4em;
  border-radius: var(--radius-sm);
}

/* 代码块：浅灰底、圆角、等宽、可横向滚动 */
.md :deep(pre) {
  margin: 0.7em 0;
  padding: var(--space-3) var(--space-4);
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  line-height: 1.5;
}

.md :deep(pre code) {
  display: block;
  padding: 0;
  background: transparent;
  border-radius: 0;
  font-size: 0.86em;
  white-space: pre;
  color: var(--text);
}

/* 表格：细边框、表头浅底、整体可横向滚动 */
.md :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  margin: 0.7em 0;
  border-collapse: collapse;
  overflow-x: auto;
  font-size: 0.9em;
}

.md :deep(th),
.md :deep(td) {
  padding: 0.4em 0.7em;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}

.md :deep(th) {
  background: var(--surface-muted);
  font-weight: 600;
  color: var(--text);
}

/* 引用块 */
.md :deep(blockquote) {
  margin: 0.7em 0;
  padding: 0.2em 0 0.2em var(--space-4);
  border-left: 3px solid var(--border-strong);
  color: var(--text-secondary);
}

.md :deep(blockquote p) {
  color: inherit;
}

/* 链接：品牌色 */
.md :deep(a) {
  color: var(--brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.md :deep(a:hover) {
  color: var(--brand-hover);
}

/* 分割线 */
.md :deep(hr) {
  height: 1px;
  margin: 1em 0;
  border: 0;
  background: var(--border);
}

/* 图片：限制最大宽度并保留圆角 */
.md :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-sm);
}
</style>
