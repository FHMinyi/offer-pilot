<script setup lang="ts">
// 底部组合输入区（composer）——从 ChatView 抽出的自包含子组件：
//   · 附件 chips（简历 / JD / 目标岗位 / 周数）+ JD 管理面板 + 内联粘贴面板；
//   · JD 库模态入口（JdLibrary，自包含 fixed 遮罩，渲染位置不影响视觉）；
//   · 分析设置（目标岗位 / 周数）与模型设置面板（BYO LLM，见 ModelSettingsPanel）；
//   · 工具行（粘贴 / JD 库 / 设置 / 模型 / 思考强度 / E3 语气滑块）；
//   · PDF 上传按钮 + 拖拽上传遮罩（useResumeUpload，解析文本写回 context.resume_text）；
//   · 输入框（Enter 发送 / Shift+Enter 换行 / 自适应高度）与发送 / 停止按钮；
//   · flash 操作反馈浮层与本会话 token 累计小字（整体内化于此）。
// 「视觉融合 + 失焦折叠为一行」的展开判定（composerExpanded）也随之内化。
//
// 与父视图（ChatView）的契约：
//   · v-model（输入文本）/ v-model:effort（思考强度）/ v-model:tone（语气强度）；
//   · context 为父级共享 reactive 对象，本组件直接改写其素材字段（项目现行风格）；
//   · send 事件不带参——父级自读输入文本、组装消息并清空（清空后的高度复位由
//     本组件 watch 输入变化自动完成）；stop 事件请求父级中止当前流式轮次；
//   · defineExpose：focusInput（编辑回填 / 新对话 / 续聊载入后的聚焦，宽屏判定由
//     父级把关）与 flash（父级提示入口，如续聊加载失败）。
import { computed, nextTick, ref, watch } from 'vue'
import { createSavedJd } from '../../api/client'
import type { ChatContext, ReasoningEffort, TurnUsage } from '../../types'
import JdLibrary from '../JdLibrary.vue'
import ModelSettingsPanel from './ModelSettingsPanel.vue'
import { fmtTokens } from '../../shared/chatModel'
import { useResumeUpload } from '../../shared/useResumeUpload'

const props = defineProps<{
  /** 对话上下文（父级共享 reactive；素材增删直接写回，见文件头契约） */
  context: ChatContext
  /** 是否正在流式生成：禁用发送 / 编辑素材等交互，发送按钮切换为「停止」 */
  streaming: boolean
  /** 输入区上方状态细条文案（onStatus 兜底；空串不渲染） */
  statusLine: string
  /** 本会话 token 用量累计（composer 顶部弱化小字） */
  sessionUsage: TurnUsage
  /** 是否已有用量可展示（无则不渲染小字行） */
  hasSessionUsage: boolean
}>()

const emit = defineEmits<{
  /** 点击发送 / Enter：不带参，父级自读输入文本组装消息 */
  (e: 'send'): void
  /** 点击停止：父级中止当前流式轮次 */
  (e: 'stop'): void
}>()

// ---------- 三个 v-model ----------
// 当前输入框文本。
const input = defineModel<string>({ required: true })
// 思考强度：随 streamChat 以 reasoning_effort 提交。
const reasoningEffort = defineModel<ReasoningEffort>('effort', { required: true })
// E3 语气强度 0=最温柔…100=最严格（持久化 ref 在父级，经 v-model:tone 写回）。
const tone = defineModel<number>('tone', { required: true })

// ---------- 思考强度选项 ----------
// 6 档：关闭 / 低 / 中 / 高 / 极高 / 最高（中英关键词并列，便于对照模型档位）。
const effortOptions: { value: ReasoningEffort; label: string }[] = [
  { value: 'off', label: '关闭' },
  { value: 'low', label: '低 low' },
  { value: 'medium', label: '中 medium' },
  { value: 'high', label: '高 high' },
  { value: 'xhigh', label: '极高 xhigh' },
  { value: 'max', label: '最高 max' },
]

// 思考强度说明文案（用于选择器旁的 ⓘ 提示）。
const effortTip =
  '思考强度对支持推理的模型生效（如 OpenAI o 系列、DeepSeek-Reasoner、Claude）；' +
  '不支持的模型本项无效，也不影响正常对话。' +
  '在多数 OpenAI 协议模型上“极高/最高”等同“高”。'

// ---------- E3 语气滑块（B5：单人设 + 语气滑块） ----------
const toneLabel = computed(() => {
  const t = tone.value
  if (t <= 20) return '最温柔'
  if (t <= 40) return '偏鼓励'
  if (t <= 60) return '平衡'
  if (t <= 80) return '偏严格'
  return '最严格'
})
const toneTip =
  '语气滑块（仅调 AI 措辞，不改分析逻辑）：左=温柔鼓励、多共情；右=严格鞭策、坦诚指出差距。' +
  '无论松紧都基于事实、不报具体 Offer 概率。可用鼠标滚轮或聚焦后方向键调节。'

const TONE_STEP = 10
function clampTone(v: number): number {
  return Math.max(0, Math.min(100, v))
}
// 鼠标滚轮调节语气：上滚=更严格(+)，下滚=更温柔(−)。流式中不拦截，留作正常页面滚动。
function onToneWheel(e: WheelEvent): void {
  if (props.streaming) return
  e.preventDefault()
  tone.value = clampTone(tone.value + (e.deltaY < 0 ? TONE_STEP : -TONE_STEP))
}

// ---------- 派生状态 ----------
// 是否已存在「可分析的素材」：有简历或至少一条 JD。
const hasAttachments = computed(
  () =>
    Boolean(props.context.resume_text && props.context.resume_text.trim()) ||
    (props.context.jd_texts?.length ?? 0) > 0,
)

// 发送按钮是否可用：流式中不可发；否则需有文本或有新素材。
const canSend = computed(
  () => !props.streaming && (input.value.trim().length > 0 || hasAttachments.value),
)

// 周数下拉选项 1~12。
const weekOptions = Array.from({ length: 12 }, (_, i) => i + 1)

// ===================================================================
//  附件 / 上下文管理
// ===================================================================

// —— 内联输入区（粘贴简历 / 添加 JD）开合与内容 ——
const pasteOpen = ref(false)
const pasteText = ref('')

function togglePaste(): void {
  pasteOpen.value = !pasteOpen.value
}

// 把内联文本设为简历。
function applyPasteAsResume(): void {
  const text = pasteText.value.trim()
  if (!text) return
  props.context.resume_text = text
  pasteText.value = ''
  pasteOpen.value = false
  flashHint('已将粘贴内容设为简历')
}

// 把内联文本作为一条 JD 追加。
function applyPasteAsJd(): void {
  const text = pasteText.value.trim()
  if (!text) return
  if (!props.context.jd_texts) props.context.jd_texts = []
  props.context.jd_texts.push(text)
  pasteText.value = ''
  pasteOpen.value = false
  flashHint('已添加 1 条 JD')
}

// —— JD 列表展开管理 ——
const jdManagerOpen = ref(false)
function toggleJdManager(): void {
  jdManagerOpen.value = !jdManagerOpen.value
}
function removeJd(index: number): void {
  props.context.jd_texts?.splice(index, 1)
  if ((props.context.jd_texts?.length ?? 0) === 0) jdManagerOpen.value = false
}

// —— JD 库（自包含模态）开合与对接 ——
const jdLibraryOpen = ref(false)
function openJdLibrary(): void {
  jdLibraryOpen.value = true
}
function closeJdLibrary(): void {
  jdLibraryOpen.value = false
}

// JD 库「加入分析」回调：把每条内容追加进 context.jd_texts 并提示已添加。
function onUseSavedJds(contents: string[]): void {
  const list = contents.map((c) => c.trim()).filter((c) => c.length > 0)
  if (list.length === 0) return
  if (!props.context.jd_texts) props.context.jd_texts = []
  props.context.jd_texts.push(...list)
  flashHint(`已添加 ${list.length} 条 JD`)
}

// 把已添加的某条 JD「存入 JD 库」：标题取前 20 字（去空白），空则「未命名 JD」。
const savingJdIndex = ref<number | null>(null)
async function saveJdToLibrary(index: number): Promise<void> {
  if (savingJdIndex.value !== null) return
  const content = props.context.jd_texts?.[index]?.trim()
  if (!content) return
  const title = content.slice(0, 20).trim() || '未命名 JD'
  savingJdIndex.value = index
  try {
    await createSavedJd({ title, content })
    flashHint('已存入 JD 库')
  } catch (err) {
    flashHint(err instanceof Error ? err.message : '存入 JD 库失败，请重试', true)
  } finally {
    savingJdIndex.value = null
  }
}

// —— 移除简历 ——
function removeResume(): void {
  props.context.resume_text = undefined
}

// —— 分析设置（目标岗位 / 周数）开合 ——
const settingsOpen = ref(false)
function toggleSettings(): void {
  settingsOpen.value = !settingsOpen.value
}

// —— 模型设置（BYO LLM）开合 ——
// 面板内容与拉取状态自包含在 ModelSettingsPanel（实例常驻，开合经 open prop）。
const modelSettingsOpen = ref(false)
function toggleModelSettings(): void {
  modelSettingsOpen.value = !modelSettingsOpen.value
}

// ---------- PDF 上传 + 拖拽 ----------
// 校验 / 上传解析 / 拖拽状态机由 useResumeUpload 承担；
// 解析出的简历全文写入 context.resume_text，反馈走 flashHint。
const { uploading, ingestResumeFile, dragOver, onDragEnter, onDragOver, onDragLeave, onDrop } =
  useResumeUpload({
    onResumeText: (text) => {
      props.context.resume_text = text
    },
    flash: flashHint,
  })

// 隐藏的 PDF 文件框。
const fileInput = ref<HTMLInputElement | null>(null)

// 触发隐藏文件框。
function triggerUpload(): void {
  if (uploading.value) return
  fileInput.value?.click()
}

// 选择 PDF → 交给统一的上传处理。
async function onFileChange(event: Event): Promise<void> {
  const el = event.target as HTMLInputElement
  const file = el.files?.[0]
  el.value = '' // 允许重复选择同一文件
  if (file) await ingestResumeFile(file)
  // 文件框关闭后焦点回到输入框：恢复 composer 展开态、衔接后续输入
  textareaRef.value?.focus()
}

// ---------- 轻量浮层提示 ----------
const hint = ref('')
const hintError = ref(false)
let hintTimer: ReturnType<typeof setTimeout> | undefined

// 短暂展示一条操作反馈，自动消失（经 defineExpose 同时供父级使用）。
function flashHint(message: string, isError = false): void {
  hint.value = message
  hintError.value = isError
  if (hintTimer) clearTimeout(hintTimer)
  hintTimer = setTimeout(() => {
    hint.value = ''
  }, 2600)
}

// ===================================================================
//  视觉融合 + 失焦折叠为一行
// ===================================================================
// composer 容器引用：用于失焦判定（焦点是否仍在容器内）。
const composerBoxRef = ref<HTMLElement | null>(null)
// composer 是否聚焦（焦点位于容器内任意元素）。
const composerFocused = ref(false)
// 是否展开：聚焦 / 打开了某面板 / 拖拽中 / 已输入文字 时展开；否则折叠为单行。
const composerExpanded = computed(
  () =>
    composerFocused.value ||
    pasteOpen.value ||
    settingsOpen.value ||
    jdManagerOpen.value ||
    dragOver.value ||
    input.value.trim().length > 0,
)
// 已附素材计数（折叠态在附件按钮上显示角标，提示「已带素材」）。
const attachmentCount = computed(
  () =>
    (props.context.resume_text && props.context.resume_text.trim() ? 1 : 0) +
    (props.context.jd_texts?.length ?? 0),
)
function onComposerFocusIn(): void {
  composerFocused.value = true
}
function onComposerFocusOut(): void {
  // 延迟到焦点转移完成后再判定：以 document.activeElement 是否仍在 composer 容器内为准。
  // 这样兼容「点击 <select> 下拉 / 原生文件框 / 非可聚焦区域」等 relatedTarget 为 null 的情形，
  // 避免与这些原生控件交互途中 composer 被误折叠。
  window.setTimeout(() => {
    const box = composerBoxRef.value
    const active = document.activeElement
    composerFocused.value = !!(
      box &&
      active &&
      active !== document.body &&
      box.contains(active)
    )
  }, 0)
}

// ---------- 输入框：Enter 发送 / Shift+Enter 换行 + 自适应高度 ----------
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    emit('send')
  }
}

// 随内容增减自适应高度（限制最大高度，超出滚动）。
function autoGrow(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

// 输入内容变化时同步高度（父级发送后清空输入文本，也经此自动复位高度）。
watch(input, () => {
  void nextTick(autoGrow)
})

// 让输入框获得焦点（等 DOM 更新后聚焦，顺带按当前内容同步高度）。
// 供父级在「编辑回填 / 新对话 / 续聊载入」后调用；
// 「仅宽屏自动聚焦（移动端不弹软键盘）」的判定由父级把关。
function focusInput(): void {
  void nextTick(() => {
    autoGrow()
    textareaRef.value?.focus()
  })
}

defineExpose({ focusInput, flash: flashHint })
</script>

<template>
  <!-- ============ 底部组合输入区（视觉融合 + 失焦折叠为一行） ============ -->
  <div class="composer">
    <!-- 本会话 token 累计小字（可选，弱化）：与气泡本轮口径一致，点「用量」进统计页 -->
    <RouterLink
      v-if="hasSessionUsage"
      class="session-usage"
      :to="{ name: 'usage' }"
      title="查看用量统计"
    >
      📊 本会话累计 {{ fmtTokens(sessionUsage.total ?? 0) }} tokens
      （输入 {{ fmtTokens(sessionUsage.input_hit + sessionUsage.input_miss) }} · 输出
      {{ fmtTokens(sessionUsage.output) }}）
    </RouterLink>
    <div
      ref="composerBoxRef"
      class="composer__box"
      :class="{
        'composer__box--expanded': composerExpanded,
        'composer__box--drag': dragOver,
      }"
      @focusin="onComposerFocusIn"
      @focusout="onComposerFocusOut"
      @dragenter="onDragEnter"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <!-- 拖拽放入提示遮罩：拖动文件到输入区时出现 -->
      <div v-if="dragOver" class="dropzone" aria-hidden="true">
        <div class="dropzone__inner">
          <span class="dropzone__icon">⬆</span>
          <span class="dropzone__text">松开以上传简历（PDF）</span>
          <span class="dropzone__hint">拖放 PDF 文件到这里即可解析为简历</span>
        </div>
      </div>

      <!-- 状态细条（onStatus 兜底，仅在无进行中工具块时出现） -->
      <div v-if="statusLine" class="status-bar" role="status" aria-live="polite">
        <span class="status-bar__dot" aria-hidden="true" />
        {{ statusLine }}
      </div>

      <!-- 操作反馈浮条 -->
      <div
        v-if="hint"
        class="flash"
        :class="{ 'flash--error': hintError }"
        role="status"
        aria-live="polite"
      >
        {{ hint }}
      </div>

      <!-- 展开区：附件 chips + 各展开面板（仅展开态渲染；折叠时只留下方输入行） -->
      <template v-if="composerExpanded">
      <!-- 附件 chips 行 -->
      <div class="chips">
        <!-- 简历 -->
        <span v-if="context.resume_text" class="chip chip--active">
          <span class="chip__icon" aria-hidden="true">📄</span>
          简历已添加
          <button
            type="button"
            class="chip__remove"
            title="移除简历"
            @click="removeResume"
          >
            ✕
          </button>
        </span>

        <!-- JD 数量（可展开管理） -->
        <button
          v-if="(context.jd_texts?.length ?? 0) > 0"
          type="button"
          class="chip chip--active chip--btn"
          :aria-expanded="jdManagerOpen"
          @click="toggleJdManager"
        >
          <span class="chip__icon" aria-hidden="true">🗂</span>
          JD ×{{ context.jd_texts?.length }}
          <span class="chip__caret" :class="{ open: jdManagerOpen }">▸</span>
        </button>

        <!-- 目标岗位 -->
        <span v-if="context.target_role" class="chip">
          <span class="chip__icon" aria-hidden="true">🎯</span>
          {{ context.target_role }}
        </span>

        <!-- 周数 -->
        <span class="chip chip--muted">
          <span class="chip__icon" aria-hidden="true">🗓</span>
          {{ context.weeks }} 周计划
        </span>
      </div>

      <!-- JD 管理面板（查看 / 存入 JD 库 / 删除某条） -->
      <div v-if="jdManagerOpen && (context.jd_texts?.length ?? 0) > 0" class="panel jd-panel">
        <ul class="jd-list">
          <li v-for="(jd, idx) in context.jd_texts" :key="idx" class="jd-row">
            <span class="jd-row__index">JD {{ idx + 1 }}</span>
            <span class="jd-row__text">{{ jd }}</span>
            <button
              type="button"
              class="jd-row__save"
              :disabled="savingJdIndex !== null"
              title="把这条 JD 存入 JD 库，便于以后复用"
              @click="saveJdToLibrary(idx)"
            >
              {{ savingJdIndex === idx ? '存入中…' : '存入 JD 库' }}
            </button>
            <button
              type="button"
              class="jd-row__remove"
              title="删除此条 JD"
              @click="removeJd(idx)"
            >
              删除
            </button>
          </li>
        </ul>
      </div>

      <!-- 内联粘贴区（设为简历 / 追加 JD） -->
      <div v-if="pasteOpen" class="panel paste-panel">
        <textarea
          v-model="pasteText"
          class="field paste-panel__area"
          rows="4"
          placeholder="在此粘贴简历全文，或粘贴一条岗位 JD 原文……"
        />
        <div class="paste-panel__actions">
          <button
            type="button"
            class="btn"
            :disabled="!pasteText.trim()"
            @click="applyPasteAsResume"
          >
            设为简历
          </button>
          <button
            type="button"
            class="btn"
            :disabled="!pasteText.trim()"
            @click="applyPasteAsJd"
          >
            添加为 JD
          </button>
          <button type="button" class="btn btn-ghost" @click="togglePaste">
            收起
          </button>
        </div>
      </div>

      <!-- 分析设置（目标岗位 / 周数） -->
      <div v-if="settingsOpen" class="panel settings-panel">
        <label class="settings-panel__field">
          <span class="settings-panel__label">目标岗位</span>
          <input
            v-model="context.target_role"
            class="field"
            type="text"
            placeholder="例如：前端实习、Java 后端、数据分析"
            autocomplete="off"
          />
        </label>
        <label class="settings-panel__field settings-panel__field--weeks">
          <span class="settings-panel__label">规划周数</span>
          <select v-model.number="context.weeks" class="field">
            <option v-for="n in weekOptions" :key="n" :value="n">{{ n }} 周</option>
          </select>
        </label>
      </div>

      </template>

      <!-- 模型设置面板：组件实例常驻（拉取状态跨开合留存），DOM 仅在
           「composer 展开 && 面板打开」时渲染——同拆分前 v-if 语义 -->
      <ModelSettingsPanel :open="composerExpanded && modelSettingsOpen" />

      <!-- 主输入行：附件按钮 + 输入框 + 发送/停止（折叠态也保留这一行） -->
      <div class="composer__row">
        <button
          type="button"
          class="composer__attach"
          :disabled="uploading || streaming"
          :title="uploading ? '解析中…' : '上传简历（PDF）'"
          aria-label="上传简历 PDF"
          @click="triggerUpload"
        >
          <span v-if="uploading" class="tool-btn__spinner" aria-hidden="true" />
          <span v-else class="composer__attach-icon" aria-hidden="true">📎</span>
          <span
            v-if="attachmentCount > 0 && !uploading"
            class="composer__attach-badge"
            :title="`已附 ${attachmentCount} 项素材`"
          >{{ attachmentCount }}</span>
        </button>
        <input
          ref="fileInput"
          class="visually-hidden"
          type="file"
          accept=".pdf"
          @change="onFileChange"
        />

        <textarea
          ref="textareaRef"
          v-model="input"
          class="entry__input"
          rows="1"
          :disabled="streaming"
          placeholder="给 OfferPilot 发消息，或直接发送以基于已添加素材开始分析…（Enter 发送，Shift+Enter 换行）"
          @keydown="onKeydown"
        />

        <button
          v-if="streaming"
          type="button"
          class="entry__send entry__send--stop"
          title="停止生成"
          @click="emit('stop')"
        >
          <span class="entry__stop-icon" aria-hidden="true" />
          停止
        </button>
        <button
          v-else
          type="button"
          class="entry__send"
          :disabled="!canSend"
          :aria-disabled="!canSend"
          title="发送"
          @click="emit('send')"
        >
          发送
        </button>
      </div>

      <!-- 工具行（仅展开态渲染）：粘贴 / JD 库 / 设置 / 模型 / 思考强度 / 语气 -->
      <div v-if="composerExpanded" class="composer__toolbar">
        <button
          type="button"
          class="tool-btn"
          :class="{ 'tool-btn--on': pasteOpen }"
          :disabled="streaming"
          :aria-expanded="pasteOpen"
          @click="togglePaste"
        >
          <span aria-hidden="true">📝</span>
          粘贴 / JD
        </button>

        <!-- JD 库：打开自包含模态，复用已保存的 JD 加入本次分析 -->
        <button
          type="button"
          class="tool-btn"
          :class="{ 'tool-btn--on': jdLibraryOpen }"
          :aria-expanded="jdLibraryOpen"
          title="从 JD 库选取已保存的岗位 JD 加入本次分析"
          @click="openJdLibrary"
        >
          <span aria-hidden="true">🗂</span>
          JD 库
        </button>

        <button
          type="button"
          class="tool-btn"
          :class="{ 'tool-btn--on': settingsOpen }"
          :aria-expanded="settingsOpen"
          @click="toggleSettings"
        >
          <span aria-hidden="true">⚙</span>
          分析设置
        </button>

        <!-- 模型设置：自定义大语言模型（provider / base_url / API Key / 三档模型） -->
        <button
          type="button"
          class="tool-btn"
          :class="{ 'tool-btn--on': modelSettingsOpen }"
          :aria-expanded="modelSettingsOpen"
          :disabled="streaming"
          @click="toggleModelSettings"
        >
          <span aria-hidden="true">🧠</span>
          模型
        </button>

        <!-- 思考强度选择器：随对话以 reasoning_effort 提交（6 档关键词标签） -->
        <label class="effort" :title="effortTip">
          <span class="effort__icon" aria-hidden="true">💭</span>
          <span class="effort__label">思考</span>
          <select v-model="reasoningEffort" class="effort__select" :disabled="streaming">
            <option v-for="opt in effortOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
          <span class="effort__info" :title="effortTip" aria-hidden="true">ⓘ</span>
        </label>

        <!-- E3 语气滑块：仅调 AI 措辞（鼓励⟷鞭策），随对话以 context.tone 提交。
             桌面端支持鼠标滚轮（@wheel）与方向键（原生 range 聚焦后即可）。 -->
        <label class="tone" :title="toneTip" @wheel="onToneWheel">
          <span class="tone__icon" aria-hidden="true">🎚️</span>
          <span class="tone__label">语气</span>
          <input
            v-model.number="tone"
            class="tone__range"
            type="range"
            min="0"
            max="100"
            step="10"
            :disabled="streaming"
            :aria-label="`语气强度 ${tone}/100（${toneLabel}）`"
          />
          <span class="tone__value">{{ toneLabel }}</span>
        </label>
      </div>
    </div>

    <!-- JD 库（自包含模态，fixed 遮罩不受此处 DOM 位置影响）：
         工具行的「JD 库」按钮打开；选条后加入本次分析 -->
    <JdLibrary :open="jdLibraryOpen" @close="closeJdLibrary" @use="onUseSavedJds" />
  </div>
</template>

<style scoped>
/* ===================================================================
   底部组合输入区
   =================================================================== */
.composer {
  flex-shrink: 0;
  position: sticky;
  bottom: 0;
  /* 顶部渐隐过渡，避免内容硬切 */
  background: linear-gradient(
    to bottom,
    rgba(246, 247, 249, 0) 0%,
    var(--bg) 18%
  );
  padding-top: var(--space-3);
}

/* 本会话 token 累计小字：弱化、居中、点击进统计页 */
.session-usage {
  display: block;
  margin: 0 auto var(--space-2);
  text-align: center;
  font-size: 0.72rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.session-usage:hover {
  color: var(--brand);
}

/* 融合输入盒：单一圆角容器，内含附件 / 输入 / 发送 / 工具，视觉浑然一体。
   折叠态（未聚焦且空）只显主输入行一行；展开态显现 chips / 面板 / 工具行。 */
.composer__box {
  position: relative; /* 供拖拽提示遮罩定位 */
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: 8px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    background 0.15s ease;
}

/* 展开态：更强阴影 + 更宽松内边距 */
.composer__box--expanded {
  gap: var(--space-3);
  padding: var(--space-3);
  box-shadow: var(--shadow-md);
}

/* 聚焦：整盒高亮描边（输入框本身无边框，焦点环落在盒上） */
.composer__box:focus-within {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

/* 拖拽文件悬停态：高亮 + 虚线描边 */
.composer__box--drag {
  border-color: var(--brand);
  border-style: dashed;
  background: var(--brand-soft);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

/* ---------- 主输入行（附件 + 输入框 + 发送） ---------- */
.composer__row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

/* 附件（上传）按钮：盒内 ghost 圆角图标按钮，带素材角标 */
.composer__attach {
  position: relative;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 1.05rem;
  transition:
    border-color var(--transition),
    color var(--transition),
    background var(--transition);
}

.composer__attach:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

.composer__attach:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.composer__attach-icon {
  line-height: 1;
}

/* 已附素材角标 */
.composer__attach-badge {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-pill);
  background: var(--brand);
  color: var(--text-on-brand);
  font-size: 0.66rem;
  font-weight: 700;
  line-height: 1;
  box-shadow: var(--shadow-sm);
}

/* ---------- 工具行（盒内底部，仅展开态显示） ---------- */
.composer__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}

/* 拖拽放入提示遮罩：覆盖整个输入区，扩大可放置范围并提示 */
.dropzone {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
  background: var(--brand-soft); /* 不支持 color-mix 时的回退 */
  background: color-mix(in srgb, var(--brand-soft) 92%, transparent);
  backdrop-filter: blur(1px);
  pointer-events: none; /* 让拖拽事件继续命中底层容器，保证 drop 生效 */
}

.dropzone__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  border: 2px dashed var(--brand);
  border-radius: var(--radius-lg);
  color: var(--brand-active);
  text-align: center;
}

.dropzone__icon {
  font-size: 1.6rem;
  line-height: 1;
}

.dropzone__text {
  font-size: 1rem;
  font-weight: 600;
}

.dropzone__hint {
  font-size: 0.82rem;
  color: var(--text-secondary);
}

/* 状态细条 */
.status-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px 12px;
  border-radius: var(--radius);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.85rem;
}

.status-bar__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
  animation: op-pulse 1.4s ease-in-out infinite;
}

/* 操作反馈浮条 */
.flash {
  padding: 6px 12px;
  border-radius: var(--radius);
  background: var(--success-soft);
  color: var(--success);
  font-size: 0.85rem;
  font-weight: 550;
}

.flash--error {
  background: var(--danger-soft);
  color: var(--danger);
}

/* ---------- 附件 chips ---------- */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: 0.82rem;
  font-weight: 550;
  max-width: 100%;
}

.chip--active {
  background: var(--brand-soft);
  border-color: #c7d8ff;
  color: var(--brand-active);
}

.chip--muted {
  color: var(--text-muted);
}

.chip--btn {
  cursor: pointer;
  transition: background var(--transition);
}

.chip--btn:hover {
  background: #e3edff;
}

.chip__icon {
  font-size: 0.9em;
}

.chip__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  font-size: 0.7rem;
  opacity: 0.7;
}

.chip__remove:hover {
  background: rgba(0, 0, 0, 0.08);
  opacity: 1;
}

.chip__caret {
  font-size: 0.7rem;
  transition: transform var(--transition);
}

.chip__caret.open {
  transform: rotate(90deg);
}

/* ---------- 展开面板（JD / 粘贴 / 设置）通用 ----------
   注意：ModelSettingsPanel 内部持有 .panel / .settings-panel 同名规则的
   本地副本（scoped 边界命不中子组件内部），改动时两处保持一致。 */
.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-muted);
  padding: var(--space-3);
}

/* JD 管理 */
.jd-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 220px;
  overflow-y: auto;
}

.jd-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.jd-row__index {
  flex-shrink: 0;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--brand-active);
}

.jd-row__text {
  flex: 1;
  min-width: 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jd-row__save {
  flex-shrink: 0;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 0.8rem;
  transition:
    border-color var(--transition),
    color var(--transition),
    background var(--transition);
}

.jd-row__save:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

.jd-row__save:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.jd-row__remove {
  flex-shrink: 0;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.8rem;
}

.jd-row__remove:hover {
  border-color: var(--danger);
  color: var(--danger);
  background: var(--danger-soft);
}

/* 粘贴面板 */
.paste-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.paste-panel__area {
  background: var(--surface);
  line-height: 1.6;
}

.paste-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

/* 设置面板 */
.settings-panel {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.settings-panel__field {
  flex: 1;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.settings-panel__field--weeks {
  flex: 0 0 140px;
  min-width: 140px;
}

.settings-panel__label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
}

.settings-panel .field {
  background: var(--surface);
}

/* ---------- 工具按钮（盒内工具行内） ---------- */
.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.82rem;
  font-weight: 550;
  transition:
    background var(--transition),
    border-color var(--transition),
    color var(--transition);
}

.tool-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

.tool-btn--on {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

.tool-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tool-btn__spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: op-spin 0.7s linear infinite;
}

/* 思考强度选择器：与工具按钮同一视觉语言（ghost） */
.effort {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px 4px 10px;
  margin-left: auto; /* 推到工具行最右侧 */
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.82rem;
  font-weight: 550;
}

.effort:hover {
  background: var(--surface-muted);
}

.effort__icon {
  font-size: 0.9em;
}

.effort__select {
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 0.85rem;
  font-weight: 600;
  padding: 2px 4px;
  cursor: pointer;
}

.effort__select:focus {
  outline: none;
}

.effort__select:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

/* 说明小图标：弱化、可悬停查看 title 文案 */
.effort__info {
  font-size: 0.8rem;
  color: var(--text-muted);
  cursor: help;
  user-select: none;
}

.effort__info:hover {
  color: var(--text-secondary);
}

/* ---------- E3 语气滑块 ---------- */
.tone {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.82rem;
  font-weight: 550;
}

.tone:hover {
  background: var(--surface-muted);
}

.tone__icon {
  font-size: 0.9em;
}

.tone__range {
  width: 84px;
  accent-color: var(--brand);
  cursor: pointer;
}

.tone__range:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.tone__value {
  min-width: 2.6em;
  color: var(--text);
  font-weight: 600;
}

/* ---------- 输入框（盒内无边框，焦点环由 .composer__box 承载） ---------- */
.entry__input {
  flex: 1;
  min-width: 0;
  max-height: 180px;
  padding: 8px 6px;
  border: 0;
  background: transparent;
  line-height: 1.6;
  resize: none;
  overflow-y: auto;
}

.entry__input:focus {
  outline: none;
}

.entry__input:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.entry__send {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 42px;
  padding: 0 20px;
  border: 1px solid var(--brand);
  border-radius: var(--radius);
  background: var(--brand);
  color: var(--text-on-brand);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
  transition:
    background var(--transition),
    border-color var(--transition),
    opacity var(--transition),
    transform var(--transition);
}

.entry__send:hover:not(:disabled) {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.entry__send:active:not(:disabled) {
  transform: translateY(1px);
}

.entry__send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.entry__send--stop {
  background: var(--surface);
  border-color: var(--border-strong);
  color: var(--text);
}

.entry__send--stop:hover {
  background: var(--danger-soft);
  border-color: var(--danger);
  color: var(--danger);
}

.entry__stop-icon {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: currentColor;
}

/* ---------- 隐藏的原生文件框 ---------- */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* ---------- 动画降级 ----------
   keyframes（op-spin / op-pulse）在 styles/main.css 全局；
   用户偏好减少动效时，本组件的动效元素全部静止。 */
@media (prefers-reduced-motion: reduce) {
  .tool-btn__spinner {
    animation: none;
  }
  .status-bar__dot {
    animation: none;
  }
}

/* ---------- 响应式 ---------- */
/* 窄屏（<960px，与 ChatView 的两栏堆叠断点一致）：
   composer 改为静态流式排布（取消 sticky），使「对话 → composer → 报告面板」
   按自然顺序堆叠，整页一起滚动，避免 sticky composer 浮盖下方报告。 */
@media (max-width: 960px) {
  .composer {
    position: static;
    /* 去掉为 sticky 准备的顶部渐隐背景，避免在流式排布下出现突兀渐变 */
    background: transparent;
  }
}

@media (max-width: 640px) {
  .composer__inner {
    padding: var(--space-3);
  }

  .entry__send {
    padding: 0 14px;
  }
}
</style>
