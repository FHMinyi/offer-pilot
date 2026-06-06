<script setup lang="ts">
// 面经复盘卡（轨道 F1 · 碰壁期闭环输入端）：
// 贴一段面试复盘 → 后端抽盲区(LLM/规则) + 权重回灌(命中任务提权并拉到今天) →
// 卡内展示识别到的盲区与「建议加练」，并 emit('replayed') 让父组件刷新任务清单。
import { ref } from 'vue'
import type { BlindSpot, InterviewReplay } from '../types'
import { createInterview } from '../api/client'

const emit = defineEmits<{
  (e: 'replayed', result: InterviewReplay): void
  (e: 'error', msg: string): void
}>()

const open = ref(false)
const content = ref('')
const company = ref('')
const role = ref('')
const submitting = ref(false)
const result = ref<InterviewReplay | null>(null)

const SEV_LABEL: Record<BlindSpot['severity'], string> = { high: '严重', mid: '一般', low: '轻微' }

async function submit(): Promise<void> {
  const text = content.value.trim()
  if (!text || submitting.value) return
  submitting.value = true
  result.value = null // 清掉上次结果，避免本次失败时仍展示陈旧的「已回灌」
  try {
    const res = await createInterview({
      content: text,
      company: company.value.trim(),
      role: role.value.trim(),
    })
    result.value = res
    content.value = ''
    emit('replayed', res)
  } catch (err) {
    emit('error', err instanceof Error ? err.message : '提交面经失败，请重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="ir">
    <button type="button" class="ir__head" :aria-expanded="open" @click="open = !open">
      <span class="ir__title">📝 面经复盘</span>
      <span class="ir__hint">把面试碰壁转成下一步重点</span>
      <span class="ir__chev" aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
    </button>

    <div v-if="open" class="ir__body">
      <div class="ir__meta">
        <input v-model="company" class="field" type="text" placeholder="公司（可空）" />
        <input v-model="role" class="field" type="text" placeholder="岗位（可空）" />
      </div>
      <textarea
        v-model="content"
        class="field ir__text"
        rows="4"
        placeholder="贴一段面试复盘：被问到什么、哪里答不上来、哪些点不熟……例如「问了 React Hooks 原理和 TypeScript 泛型，都答得磕磕绊绊」"
      />
      <div class="ir__actions">
        <span class="muted ir__tip">识别盲区后，会把命中的未完成任务标为「重点」并提到今天。</span>
        <button
          type="button"
          class="btn btn--primary"
          :disabled="submitting || !content.trim()"
          @click="submit"
        >
          {{ submitting ? '分析中…' : '复盘并回灌' }}
        </button>
      </div>

      <!-- 回灌结果 -->
      <div v-if="result" class="ir__result">
        <p class="ir__result-line">
          识别到 <strong>{{ result.interview.blind_spots.length }}</strong> 个盲区<span
            v-if="result.boosted_tasks.length"
            >，<strong>{{ result.boosted_tasks.length }}</strong> 条任务已标为重点并提到今天</span
          ><span v-else>，当前计划暂无可命中的任务</span>。
        </p>
        <div v-if="result.interview.blind_spots.length" class="ir__chips">
          <span
            v-for="s in result.interview.blind_spots"
            :key="s.skill_key"
            class="chip"
            :class="[`chip--${s.severity}`, { 'chip--matched': s.matched }]"
            :title="s.matched ? '已回灌到计划任务' : '当前计划未覆盖，建议加练'"
          >
            {{ s.skill_name }}
            <span class="chip__sev">{{ SEV_LABEL[s.severity] }}</span>
          </span>
        </div>
        <p v-if="result.unmatched_skills.length" class="ir__unmatched muted">
          💡 计划未覆盖：{{ result.unmatched_skills.map((s) => s.skill_name).join('、') }}（建议加练）
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ir {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ir__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.ir__title {
  font-weight: 700;
  color: var(--text);
}

.ir__hint {
  font-size: 0.78rem;
  color: var(--text-muted);
}

.ir__chev {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.ir__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ir__meta {
  display: flex;
  gap: var(--space-2);
}

.ir__text {
  resize: vertical;
}

.ir__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.ir__tip {
  font-size: 0.78rem;
}

.ir__result {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border);
}

.ir__result-line {
  margin: 0;
  font-size: 0.86rem;
  color: var(--text-secondary);
}

.ir__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 0.76rem;
  background: var(--surface-muted);
  color: var(--text-secondary);
  border: 1px solid transparent;
}

/* 命中任务（已回灌）的盲区描边强调；未命中保持弱化 */
.chip--matched {
  border-color: currentColor;
}

.chip--high {
  background: var(--danger-soft);
  color: var(--danger);
}

.chip--mid {
  background: var(--warning-soft);
  color: var(--warning);
}

.chip--low {
  background: var(--surface-muted);
  color: var(--text-muted);
}

.chip__sev {
  opacity: 0.8;
  font-size: 0.68rem;
}

.ir__unmatched {
  margin: 0;
  font-size: 0.8rem;
}
</style>
