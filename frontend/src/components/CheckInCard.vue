<script setup lang="ts">
// 今日打卡卡片（里程碑一）：心情单选 + 一句话总结 + 投入分钟数。
// completed_task_ids 由父传入（当日已完成的 task.id）。提交走 upsertCheckIn（同日覆盖）。
import { ref, watch } from 'vue'
import type { CheckIn } from '../types'
import { upsertCheckIn } from '../api/client'
import { localTodayIso } from '../shared/journey'

const props = defineProps<{
  completedTaskIds: number[]
  initial?: CheckIn | null // 今日已打卡则回填
}>()
const emit = defineEmits<{
  (e: 'saved', checkin: CheckIn): void
  (e: 'error', msg: string): void
}>()

const MOODS = [
  { key: 'down', icon: '😣', label: '低落' },
  { key: 'meh', icon: '😐', label: '一般' },
  { key: 'good', icon: '🙂', label: '不错' },
  { key: 'great', icon: '😄', label: '很好' },
  { key: 'fire', icon: '🔥', label: '燃' },
]

const mood = ref('')
const note = ref('')
const minutes = ref<number>(0)
const saving = ref(false)
const savedToday = ref(false)

// 回填今日已有打卡
watch(
  () => props.initial,
  (ci) => {
    if (ci) {
      mood.value = ci.mood || ''
      note.value = ci.note || ''
      minutes.value = ci.minutes || 0
      savedToday.value = true
    }
  },
  { immediate: true },
)

function pickMood(key: string): void {
  mood.value = mood.value === key ? '' : key
}

async function submit(): Promise<void> {
  saving.value = true
  try {
    const ci = await upsertCheckIn({
      date: localTodayIso(),
      mood: mood.value,
      note: note.value.trim(),
      minutes: Number(minutes.value) || 0,
      completed_task_ids: props.completedTaskIds,
    })
    savedToday.value = true
    emit('saved', ci)
  } catch (err) {
    emit('error', err instanceof Error ? err.message : '打卡失败，请重试')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="checkin stack">
    <div class="checkin__head">
      <span class="checkin__title">今日打卡</span>
      <span v-if="savedToday" class="checkin__badge">已记录 · 可更新</span>
    </div>

    <div class="checkin__moods" role="group" aria-label="今日心情">
      <button
        v-for="m in MOODS"
        :key="m.key"
        type="button"
        class="mood"
        :class="{ 'mood--active': mood === m.key }"
        :title="m.label"
        @click="pickMood(m.key)"
      >
        <span class="mood__icon" aria-hidden="true">{{ m.icon }}</span>
      </button>
    </div>

    <textarea
      v-model="note"
      class="field checkin__note"
      rows="2"
      placeholder="一句话总结今天（可空）"
    />

    <label class="checkin__minutes">
      <span class="checkin__minutes-label">今日投入</span>
      <input v-model.number="minutes" class="field" type="number" min="0" max="1440" />
      <span class="checkin__minutes-unit">分钟</span>
    </label>

    <div class="row">
      <span class="muted checkin__done-count">已完成 {{ completedTaskIds.length }} 项任务</span>
      <button type="button" class="btn btn--primary checkin__save" :disabled="saving" @click="submit">
        {{ saving ? '保存中…' : savedToday ? '更新打卡' : '完成打卡' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.checkin {
  gap: var(--space-3);
}

.checkin__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.checkin__title {
  font-weight: 700;
  color: var(--text);
}

.checkin__badge {
  font-size: 0.74rem;
  color: var(--success);
  background: var(--surface-muted);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.checkin__moods {
  display: flex;
  gap: var(--space-2);
}

.mood {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  cursor: pointer;
  transition:
    border-color var(--transition),
    background var(--transition),
    transform var(--transition);
}

.mood:hover {
  border-color: var(--brand);
}

.mood--active {
  border-color: var(--brand);
  background: var(--brand-soft);
  transform: translateY(-1px);
}

.mood__icon {
  font-size: 1.25rem;
  line-height: 1;
}

.checkin__note {
  resize: vertical;
}

.checkin__minutes {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.checkin__minutes-label {
  font-size: 0.86rem;
  color: var(--text-secondary);
}

.checkin__minutes .field {
  width: 96px;
}

.checkin__minutes-unit {
  font-size: 0.86rem;
  color: var(--text-muted);
}

.checkin__save {
  margin-left: auto;
}

.checkin__done-count {
  font-size: 0.82rem;
}
</style>
