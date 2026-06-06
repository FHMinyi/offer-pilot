<script setup lang="ts">
// 可勾选任务清单（里程碑一闭环核心）。
// todo⇄done 乐观切换（以 task.id 调 patchTask，失败回滚并 emit error）；
// 软删 skipped 不展示；doing 保留样式钩子。视觉沿用报告卡 .check-list 语言。
import { computed } from 'vue'
import type { Task } from '../types'
import { patchTask } from '../api/client'
import { KIND_ICON, KIND_LABEL } from '../shared/journey'

const props = withDefaults(
  defineProps<{
    tasks: Task[]
    /** 扁平单列表（不按周分组），用于「今日任务」 */
    flat?: boolean
    /** 在任务行展示 planned_date 日期徽标 */
    showDate?: boolean
  }>(),
  { flat: false, showDate: false },
)
const emit = defineEmits<{
  (e: 'changed', task: Task): void
  (e: 'error', msg: string): void
}>()

// 跳过系统软删 skipped；按周分组、周内按 order_index。
const byWeek = computed(() => {
  const m = new Map<number, Task[]>()
  for (const t of props.tasks) {
    if (t.status === 'skipped') continue
    if (!m.has(t.week)) m.set(t.week, [])
    m.get(t.week)!.push(t)
  }
  for (const arr of m.values()) arr.sort((a, b) => a.order_index - b.order_index)
  return [...m.entries()].sort((a, b) => a[0] - b[0])
})

// 扁平模式：去 skipped，按 (week, order_index) 排一列。
const flatList = computed(() =>
  props.tasks
    .filter((t) => t.status !== 'skipped')
    .sort((a, b) => a.week - b.week || a.order_index - b.order_index),
)

/** planned_date(YYYY-MM-DD) → 简短「M/D」徽标。 */
function shortDate(iso: string | null): string {
  if (!iso) return ''
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${Number(m[1])}/${Number(m[2])}` : ''
}

// 统一分组：flat 模式=单组无标题；否则按周分组。
const groups = computed<{ week: number | null; items: Task[] }[]>(() =>
  props.flat
    ? [{ week: null, items: flatList.value }]
    : byWeek.value.map(([week, items]) => ({ week, items })),
)

async function toggle(task: Task): Promise<void> {
  const nextStatus: Task['status'] = task.status === 'done' ? 'todo' : 'done'
  const prevStatus = task.status
  const prevDone = task.done
  // 乐观更新
  task.status = nextStatus
  task.done = nextStatus === 'done'
  try {
    const updated = await patchTask(task.id, { status: nextStatus })
    task.status = updated.status
    task.done = updated.done
    task.done_at = updated.done_at
    emit('changed', updated)
  } catch (err) {
    task.status = prevStatus // 回滚
    task.done = prevDone
    emit('error', err instanceof Error ? err.message : '更新任务失败，请重试')
  }
}
</script>

<template>
  <div class="checklist stack">
    <section v-for="(g, gi) in groups" :key="g.week ?? `flat-${gi}`" class="checklist__week">
      <h4 v-if="g.week !== null" class="checklist__week-title">第 {{ g.week }} 周</h4>
      <ul class="check-list">
        <li
          v-for="t in g.items"
          :key="t.id"
          class="check-item"
          :class="{
            'check-item--done': t.done,
            'check-item--doing': t.status === 'doing',
            'check-item--atrisk': t.weight === 0 && !t.done,
            'check-item--focus': t.weight >= 2 && !t.done,
          }"
        >
          <label class="check-item__label">
            <input
              type="checkbox"
              class="check-item__box"
              :checked="t.done"
              @change="toggle(t)"
            />
            <span class="check-item__kind" :title="KIND_LABEL[t.kind]" aria-hidden="true">{{
              KIND_ICON[t.kind]
            }}</span>
            <span class="check-item__title">{{ t.title }}</span>
            <span
              v-if="t.weight === 0 && !t.done"
              class="check-item__flag"
              title="已多次顺延，优先级下调"
              >⚠ 顺延</span
            >
            <span
              v-else-if="t.weight >= 2 && !t.done"
              class="check-item__focus"
              title="面试盲区 · 重点强化"
              >🎯 重点</span
            >
            <span v-if="showDate && t.planned_date" class="check-item__date">{{
              shortDate(t.planned_date)
            }}</span>
          </label>
        </li>
      </ul>
    </section>
    <p v-if="!groups.length || !groups[0].items.length" class="muted checklist__empty">
      暂无可执行任务。
    </p>
  </div>
</template>

<style scoped>
.checklist {
  gap: var(--space-4);
}

.checklist__week-title {
  margin: 0 0 var(--space-2);
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text-secondary);
}

.check-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.check-item {
  border-radius: var(--radius);
  transition: background var(--transition);
}

.check-item:hover {
  background: var(--surface-muted);
}

.check-item__label {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 8px 10px;
  cursor: pointer;
}

.check-item__box {
  margin-top: 2px;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  accent-color: var(--brand);
  cursor: pointer;
}

.check-item__kind {
  flex-shrink: 0;
  font-size: 0.95em;
  opacity: 0.85;
}

.check-item__title {
  flex: 1;
  min-width: 0;
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--text);
}

.check-item--done .check-item__title {
  color: var(--text-muted);
  text-decoration: line-through;
}

/* doing：里程碑二纠偏会写入，预留高亮钩子 */
.check-item--doing {
  background: var(--brand-soft);
}

/* 已多次顺延（weight 归 0）：弱化为至危态 */
.check-item--atrisk .check-item__title {
  color: var(--text-muted);
}

.check-item__flag {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--warning);
}

/* 面试盲区回灌（weight 提升）：强调为重点（F1） */
.check-item--focus {
  background: var(--brand-soft);
}

.check-item__focus {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--brand);
}

.check-item__date {
  flex-shrink: 0;
  margin-left: auto;
  font-size: 0.74rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.checklist__empty {
  margin: 0;
}
</style>
