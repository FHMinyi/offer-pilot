<script setup lang="ts">
// 掌握度检验抽屉（费曼/出题判定 · 把校验前移到学习环节）：
// 任务行点「检验掌握 ▸」→ 右侧抽屉 → 费曼复述 或 AI 出题判定 → 就地标记。
// AI 当教练不当法官：用户对「我已掌握」始终有最终决定权；AI 不可用（available=false）
// 时不卡死，弱化输入/反馈区并突出「我已掌握 ⭐」手动标记。判定一次性返回（非流式）。
import { computed, ref, watch } from 'vue'
import type {
  BlindSpot,
  MasteryJudgeOut,
  MasteryMode,
  MasteryQuestion,
  ReasoningEffort,
  Task,
} from '../types'
import { generateQuiz, judgeFeynman, judgeQuiz, masterTask } from '../api/client'
import { localTodayIso } from '../shared/journey'
// localStorage 持久化 ref 统一范式（读取容错 + watch 写回），见 usePersistedRef.ts
import { usePersistedRef } from '../shared/usePersistedRef'

const props = withDefaults(
  defineProps<{
    /** 非 null 即打开（被检验的 learn 任务） */
    task: Task | null
    /** E3 语气强度 0~100（MVP 仅留接口，暂未随判定提交） */
    tone?: number
  }>(),
  { tone: 50 },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'mastered', task: Task): void
  (e: 'error', msg: string): void
}>()

const SEV_LABEL: Record<BlindSpot['severity'], string> = { high: '严重', mid: '一般', low: '轻微' }

// 掌握度评级映射（excellent/good=绿、fair=黄、poor=红；空串=不显示评级）
const VERDICT_META: Record<
  Exclude<MasteryJudgeOut['check']['verdict'], ''>,
  { label: string; cls: string }
> = {
  excellent: { label: '掌握扎实', cls: 'verdict--good' },
  good: { label: '基本掌握', cls: 'verdict--good' },
  fair: { label: '还有缺口', cls: 'verdict--fair' },
  poor: { label: '需要加练', cls: 'verdict--poor' },
}

// ---------- 模式与输入态 ----------
const mode = ref<MasteryMode>('feynman')
const feynmanText = ref('')
const questions = ref<MasteryQuestion[]>([])
const answers = ref<string[]>([])
const quizLoaded = ref(false) // 出题是否已拉取（避免重复请求）

// ---------- 请求态 ----------
const loadingQuiz = ref(false)
const judging = ref(false)
const mastering = ref(false)
const localError = ref('')
const result = ref<MasteryJudgeOut | null>(null)

// AI 是否可用：从最近一次判定/出题回包读取；未判定前视为可用（true）。
const aiAvailable = ref(true)

// ---------- 判定推理强度（💭思考）----------
// 6 档复用 ChatView effortOptions 标签；随判定/出题请求透传 reasoning_effort。
// 跨会话偏好，持久化 op.mastery-effort（裸枚举字符串，读取做枚举校验，非法值回退 medium）。
const effortOptions: { value: ReasoningEffort; label: string }[] = [
  { value: 'off', label: '关闭' },
  { value: 'low', label: '低 low' },
  { value: 'medium', label: '中 medium' },
  { value: 'high', label: '高 high' },
  { value: 'xhigh', label: '极高 xhigh' },
  { value: 'max', label: '最高 max' },
]

const masteryEffort = usePersistedRef<ReasoningEffort>('op.mastery-effort', () => 'medium', {
  parse: (raw) => (effortOptions.some((o) => o.value === raw) ? (raw as ReasoningEffort) : undefined),
})

const open = computed(() => props.task !== null)

// 当前 verdict 的展示元数据（空串=不显示评级徽章）
const verdictMeta = computed(() => {
  const v = result.value?.check.verdict ?? ''
  return v ? VERDICT_META[v] : null
})

// 打开新任务时重置全部瞬态；关闭不必清（下次打开会重置）。
watch(
  () => props.task?.id,
  (id) => {
    if (id == null) return
    mode.value = 'feynman'
    feynmanText.value = ''
    questions.value = []
    answers.value = []
    quizLoaded.value = false
    loadingQuiz.value = false
    judging.value = false
    mastering.value = false
    localError.value = ''
    result.value = null
    aiAvailable.value = true
  },
)

/** 切到出题模式：若未拉过题则首次拉取。 */
async function switchMode(next: MasteryMode): Promise<void> {
  if (mode.value === next) return
  mode.value = next
  result.value = null // 切模式清掉上次反馈，避免张冠李戴
  localError.value = ''
  if (next === 'quiz' && !quizLoaded.value) {
    await loadQuiz()
  }
}

async function loadQuiz(): Promise<void> {
  if (!props.task || loadingQuiz.value) return
  loadingQuiz.value = true
  localError.value = ''
  try {
    const out = await generateQuiz(props.task.id, masteryEffort.value)
    questions.value = out.questions
    answers.value = out.questions.map(() => '')
    quizLoaded.value = true
    aiAvailable.value = out.available
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '生成题目失败，请重试'
  } finally {
    loadingQuiz.value = false
  }
}

/** 拿到判定回包后统一处理：记录可用性 + 若已升级 mastered 则就地通知父。 */
function applyJudge(out: MasteryJudgeOut): void {
  result.value = out
  aiAvailable.value = out.available
  // 后端判定通过会自动升级 mastery；此时就地通知父更新列表
  if (out.check.passed && out.task.mastered) {
    emit('mastered', out.task)
  }
}

async function submitFeynman(): Promise<void> {
  if (!props.task) return
  const text = feynmanText.value.trim()
  if (!text || judging.value) return
  judging.value = true
  localError.value = ''
  try {
    const out = await judgeFeynman(props.task.id, text, localTodayIso(), masteryEffort.value)
    applyJudge(out)
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '判定失败，请重试'
  } finally {
    judging.value = false
  }
}

async function submitQuiz(): Promise<void> {
  if (!props.task || judging.value) return
  judging.value = true
  localError.value = ''
  try {
    const out = await judgeQuiz(
      props.task.id,
      questions.value,
      answers.value,
      localTodayIso(),
      masteryEffort.value,
    )
    applyJudge(out)
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '判定失败，请重试'
  } finally {
    judging.value = false
  }
}

/** 「我已掌握 ⭐」：始终可点（即使 verdict 低或 AI 不可用）；用户最终决定权。 */
async function confirmMastered(): Promise<void> {
  if (!props.task || mastering.value) return
  mastering.value = true
  localError.value = ''
  try {
    const updated = await masterTask(props.task.id, localTodayIso())
    emit('mastered', updated)
    close()
  } catch (err) {
    localError.value = err instanceof Error ? err.message : '标记失败，请重试'
    emit('error', localError.value)
  } finally {
    mastering.value = false
  }
}

function close(): void {
  emit('close')
}

/** 仅点遮罩本身关闭（不含面板） */
function onOverlayClick(e: MouseEvent): void {
  if (e.target === e.currentTarget) close()
}
</script>

<template>
  <Transition name="mastery-fade">
    <div
      v-if="open"
      class="mastery__overlay"
      role="dialog"
      aria-modal="true"
      aria-label="检验掌握度"
      tabindex="-1"
      @click="onOverlayClick"
      @keydown.esc="close"
    >
      <aside class="mastery__panel">
        <!-- 头部 -->
        <header class="mastery__head">
          <div class="mastery__heading">
            <h2 class="mastery__title">检验掌握度</h2>
            <p v-if="task" class="mastery__subtitle">{{ task.title }}</p>
          </div>
          <button type="button" class="mastery__close" aria-label="关闭" @click="close">✕</button>
        </header>

        <div class="mastery__body">
          <!-- 模式切换 -->
          <div class="mastery__tabs" role="tablist">
            <button
              type="button"
              class="mastery__tab"
              :class="{ 'mastery__tab--on': mode === 'feynman' }"
              role="tab"
              :aria-selected="mode === 'feynman'"
              @click="switchMode('feynman')"
            >
              🗣 费曼模式
            </button>
            <button
              type="button"
              class="mastery__tab"
              :class="{ 'mastery__tab--on': mode === 'quiz' }"
              role="tab"
              :aria-selected="mode === 'quiz'"
              @click="switchMode('quiz')"
            >
              ❓ 考考我
            </button>
          </div>

          <!-- 思考强度（💭）：随判定/出题透传 reasoning_effort，对支持推理的模型生效 -->
          <div class="mastery__effort">
            <label class="mastery__effort-label" for="mastery-effort">💭 思考</label>
            <select
              id="mastery-effort"
              v-model="masteryEffort"
              class="field mastery__effort-select"
              :disabled="judging || loadingQuiz"
            >
              <option v-for="opt in effortOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- AI 降级提示（任一判定/出题返回 available=false 时） -->
          <p v-if="!aiAvailable" class="mastery__degrade">
            AI 判定未启用，可直接手动标记「我已掌握」。
          </p>

          <!-- 输入区（AI 可用时展示；不可用时弱化） -->
          <div v-show="aiAvailable" class="mastery__input">
            <!-- 费曼模式 -->
            <template v-if="mode === 'feynman'">
              <textarea
                v-model="feynmanText"
                class="field mastery__text"
                rows="6"
                placeholder="用你自己的话讲讲它的原理、关键点、适用场景…"
                :disabled="judging"
              ></textarea>
              <button
                type="button"
                class="btn btn--primary mastery__submit"
                :disabled="judging || !feynmanText.trim()"
                @click="submitFeynman"
              >
                {{ judging ? '判定中…' : '提交判定' }}
              </button>
            </template>

            <!-- 出题模式 -->
            <template v-else>
              <div v-if="loadingQuiz" class="mastery__state">
                <span class="mastery__spinner" aria-hidden="true"></span>
                <span class="muted">正在出题…</span>
              </div>
              <template v-else-if="questions.length">
                <div v-for="(q, i) in questions" :key="i" class="mastery__q">
                  <p class="mastery__q-title">{{ i + 1 }}. {{ q.q }}</p>
                  <p v-if="q.hint" class="mastery__q-hint">💡 {{ q.hint }}</p>
                  <textarea
                    v-model="answers[i]"
                    class="field mastery__qtext"
                    rows="3"
                    placeholder="写下你的回答…"
                    :disabled="judging"
                  ></textarea>
                </div>
                <button
                  type="button"
                  class="btn btn--primary mastery__submit"
                  :disabled="judging"
                  @click="submitQuiz"
                >
                  {{ judging ? '判定中…' : '提交判定' }}
                </button>
              </template>
              <p v-else class="muted">暂无题目，可手动标记或返回费曼模式。</p>
            </template>
          </div>

          <!-- 内联错误（不阻断） -->
          <p v-if="localError" class="mastery__error" role="alert">{{ localError }}</p>

          <!-- AI 反馈区 -->
          <div v-if="aiAvailable && result" class="mastery__feedback">
            <div class="mastery__feedback-head">
              <span v-if="verdictMeta" class="verdict" :class="verdictMeta.cls">{{
                verdictMeta.label
              }}</span>
              <span v-if="result.check.passed" class="mastery__passed">✓ 已判定通过</span>
            </div>
            <p v-if="result.check.feedback" class="mastery__feedback-text">
              {{ result.check.feedback }}
            </p>

            <!-- 缺口 chips（复用 InterviewReplayCard 色板） -->
            <div v-if="result.check.gaps.length" class="mastery__chips">
              <span
                v-for="g in result.check.gaps"
                :key="g.skill_key"
                class="chip"
                :class="[`chip--${g.severity}`, { 'chip--matched': g.matched }]"
                :title="g.matched ? '已回灌到计划任务' : '当前计划未覆盖，建议加练'"
              >
                {{ g.skill_name }}
                <span class="chip__sev">{{ SEV_LABEL[g.severity] }}</span>
              </span>
            </div>

            <!-- 追问 -->
            <div v-if="result.check.followup_questions.length" class="mastery__followup">
              <p class="mastery__followup-title">再想想这几个问题：</p>
              <ul class="mastery__followup-list">
                <li v-for="(fq, i) in result.check.followup_questions" :key="i">{{ fq }}</li>
              </ul>
            </div>

            <!-- 回灌提示 -->
            <p v-if="result.boosted_tasks.length" class="mastery__boosted">
              🎯 {{ result.boosted_tasks.length }} 条相关任务已标为重点
            </p>
          </div>
        </div>

        <!-- 底部：始终可点的「我已掌握」 -->
        <footer class="mastery__foot" :class="{ 'mastery__foot--hero': !aiAvailable }">
          <p v-if="!aiAvailable" class="mastery__foot-tip muted">你对「我已掌握」有最终决定权。</p>
          <button
            type="button"
            class="btn btn--primary mastery__master"
            :disabled="mastering"
            @click="confirmMastered"
          >
            {{ mastering ? '标记中…' : '我已掌握 ⭐' }}
          </button>
        </footer>
      </aside>
    </div>
  </Transition>
</template>

<style scoped>
/* 遮罩：覆盖全屏，面板靠右 */
.mastery__overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.45);
}

/* 抽屉面板：靠右、满高、内部滚动 */
.mastery__panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 480px;
  height: 100vh;
  background: var(--surface);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

/* ---------- 头部 ---------- */
.mastery__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}

.mastery__title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 650;
  color: var(--text);
}

.mastery__subtitle {
  margin: 4px 0 0;
  font-size: 0.86rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.mastery__close {
  flex-shrink: 0;
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
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}

.mastery__close:hover {
  background: var(--surface-muted);
  color: var(--text);
}

/* ---------- 主体 ---------- */
.mastery__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ---------- 模式 tab ---------- */
.mastery__tabs {
  display: flex;
  gap: var(--space-2);
  padding: 3px;
  border-radius: var(--radius);
  background: var(--surface-muted);
}

.mastery__tab {
  flex: 1;
  padding: 7px 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.86rem;
  font-weight: 550;
  cursor: pointer;
  transition:
    background var(--transition),
    color var(--transition);
}

.mastery__tab--on {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--shadow-sm);
}

/* ---------- 思考强度（💭） ---------- */
.mastery__effort {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.mastery__effort-label {
  flex-shrink: 0;
  font-size: 0.84rem;
  font-weight: 550;
  color: var(--text-secondary);
}

.mastery__effort-select {
  flex: 1;
  min-width: 0;
  font-size: 0.84rem;
}

/* ---------- 降级提示 ---------- */
.mastery__degrade {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 0.84rem;
}

/* ---------- 输入区 ---------- */
.mastery__input {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.mastery__text {
  resize: vertical;
}

.mastery__submit {
  align-self: flex-end;
}

.mastery__q {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mastery__q-title {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.5;
}

.mastery__q-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-muted);
}

.mastery__qtext {
  resize: vertical;
}

.mastery__state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) 0;
}

.mastery__spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--surface-muted);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: mastery-spin 0.8s linear infinite;
}

@keyframes mastery-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ---------- 错误 ---------- */
.mastery__error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 0.84rem;
}

/* ---------- 反馈区 ---------- */
.mastery__feedback {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-muted);
}

.mastery__feedback-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.verdict {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: 0.78rem;
  font-weight: 700;
}

.verdict--good {
  background: var(--success-soft);
  color: var(--success);
}

.verdict--fair {
  background: var(--warning-soft);
  color: var(--warning);
}

.verdict--poor {
  background: var(--danger-soft);
  color: var(--danger);
}

.mastery__passed {
  font-size: 0.8rem;
  font-weight: 650;
  color: var(--success);
}

.mastery__feedback-text {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.mastery__chips {
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

.mastery__followup-title {
  margin: 0 0 4px;
  font-size: 0.82rem;
  font-weight: 650;
  color: var(--text-secondary);
}

.mastery__followup-list {
  margin: 0;
  padding-left: 1.2em;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.84rem;
  line-height: 1.5;
  color: var(--text-secondary);
}

.mastery__boosted {
  margin: 0;
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--brand);
}

/* ---------- 底部 ---------- */
.mastery__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border);
  background: var(--surface);
}

/* 降级态：突出「我已掌握」 */
.mastery__foot--hero {
  justify-content: space-between;
}

.mastery__foot-tip {
  margin: 0;
  font-size: 0.8rem;
}

.mastery__master {
  font-weight: 600;
}

/* ---------- 过渡 ---------- */
.mastery-fade-enter-active,
.mastery-fade-leave-active {
  transition: opacity var(--transition);
}

.mastery-fade-enter-active .mastery__panel,
.mastery-fade-leave-active .mastery__panel {
  transition: transform var(--transition);
}

.mastery-fade-enter-from,
.mastery-fade-leave-to {
  opacity: 0;
}

.mastery-fade-enter-from .mastery__panel,
.mastery-fade-leave-to .mastery__panel {
  transform: translateX(100%);
}

@media (prefers-reduced-motion: reduce) {
  .mastery-fade-enter-active .mastery__panel,
  .mastery-fade-leave-active .mastery__panel {
    transition: none;
  }
}

/* ---------- 窄屏：全宽抽屉 ---------- */
@media (max-width: 540px) {
  .mastery__panel {
    max-width: none;
  }
}
</style>
