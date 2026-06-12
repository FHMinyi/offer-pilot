<script setup lang="ts">
// 对话式主界面（路由 /）——OfferPilot 的产品新门面。
//
// 职责概览：
//   · 以聊天形式承载「上传简历 / 添加 JD / 设定目标岗位与周数 → 发起分析」全流程。
//   · 用户气泡靠右、助手气泡靠左；助手回复以【有序 blocks】驱动渲染，
//     严格按事件到达顺序交错展示「对话 → 工具 → 对话 → 报告」。
//   · 布局为左右两栏：左栏=消息滚动区 + 底部「组合输入区」（composer）；
//     右栏=报告侧边面板，sticky 展示【最新】一份匹配分析的【紧凑摘要】（环形匹配度 +
//     目标岗位 + 简述 + 「查看完整报告」主按钮），不再内联整份 <AnalysisReport>；
//     完整报告在 /result/:id 页（全展开）。面板可「隐藏」(reportPanelOpen=false)：
//     隐藏后右栏消失、聊天区占满宽度，并在角落显示「📊 报告」悬浮角标以便重新展开；
//     新报告到达时自动展开（reportPanelOpen=true）。消息流里的 report block 不再内联
//     整卡渲染，改为紧凑「引用 chip」，点击让报告面板滚到顶并短暂高亮（若面板被隐藏则
//     先展开）。窄屏（<960px）两栏纵向堆叠，报告面板移到对话下方且非 sticky。
//   · composer 的 JD 操作区接入「JD 库」（自包含模态）：可把已存 JD 加入本次分析，
//     也可把当前已添加的某条 JD 存入库（createSavedJd）。
//   · 智能滚动只作用于左栏消息容器（scrollRef），右栏不影响贴底判断。
//
// 关键设计——助手消息的有序 blocks 模型：
//   原先把「文本」与「工具数组」分开存放，渲染时文字堆下面、工具堆上面，
//   无法还原真实发生顺序。现改为单一有序数组 blocks[]，每个事件「追加到末尾 /
//   更新末尾同类块」，从而严格保留交错顺序（见 runChat 内各 handler）。
//   发请求时仅把每条消息投影为纯文本（assistant 取其所有 text 块拼接），
//   工具 / 思考 / 报告不回传后端。
//
// SSE 各回调只负责「更新某条助手消息的响应式对象」，与模板渲染解耦（见 runChat）。
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createSavedJd,
  fetchLLMModels,
  getConversation,
  saveConversation,
  streamChat,
  uploadResume,
} from '../api/client'
import type {
  AnalysisResult,
  ChatContext,
  ChatMessage,
  ChatPersistContext,
  PersistedBlock,
  PersistedTurn,
  ReasoningEffort,
  SearchResultItem,
  TurnUsage,
  WeekItem,
} from '../types'
import JdLibrary from '../components/JdLibrary.vue'
import MarkdownText from '../components/MarkdownText.vue'
import ScoreRing from '../components/ui/ScoreRing.vue'
import {
  newChatSignal,
  notifyConversationsChanged,
  reportNav,
  openReportSignal,
  isWide,
} from '../shared/appState'
// 自定义大语言模型（BYO LLM）：全局配置单例 + 生效覆盖（localStorage 持久化见 llmConfig.ts）
import { llmConfig, effectiveOverride } from '../shared/llmConfig'

// ---------- 助手消息的有序 block 模型 ----------
// 一个助手回合由若干有序 block 组成，渲染严格按数组顺序输出。
type AssistantBlock =
  // 思考过程（markdown，默认折叠）
  | { kind: 'reasoning'; text: string }
  // 普通回复（markdown）
  | { kind: 'text'; text: string }
  // 工具活动；status=最后一条子步骤文案（仅进行中时有意义）；
  // steps=累积的「分析过程日志」（每行一条，按到达顺序追加，完成后保留供回看）；
  // query/results 仅 web_search：搜索关键词与结果列表；resultsOpen=结果折叠态（瞬态，不持久化）
  | {
      kind: 'tool'
      id: string
      name: string
      label: string
      ok?: boolean
      status?: string
      steps?: string[]
      query?: string
      results?: SearchResultItem[]
      resultsOpen?: boolean
    }
  // 结构化报告卡
  | { kind: 'report'; analysis_run_id: number; result: AnalysisResult }

// ---------- 渲染用消息结构 ----------
// 用户消息：仅文本。
interface UserTurn {
  role: 'user'
  text: string
}
// 助手消息：有序 blocks + 可选错误 + 流式标记 + 折叠态。
interface AssistantTurn {
  role: 'assistant'
  blocks: AssistantBlock[]
  error?: string
  streaming: boolean
  // 触发本轮的对话历史快照（供「重试」复用，不含本占位消息）。
  requestMessages?: ChatMessage[]
  // 各 reasoning 块的展开态，按块在 blocks 中的下标索引。
  // 流式期间默认展开、本轮结束后自动折叠；用户可手动点击切换。
  reasoningOpen: Record<number, boolean>
  // 发起本轮时所选的思考强度（用于结束时判断「应有思考却无思考」）。
  effort?: ReasoningEffort
  // 本轮结束后置位：发起时强度 !== 'off' 但模型未输出任何 reasoning 块。
  noThinking?: boolean
  // 本轮 token 用量（SSE usage 事件到达后置位）：气泡小字展示输入(命中)/输出。
  usage?: TurnUsage
}
type ChatTurn = UserTurn | AssistantTurn

// ---------- 核心状态 ----------
// 对话消息列表（渲染源）。欢迎语为静态空状态，不入此列表，故不会回传后端。
const turns = reactive<ChatTurn[]>([])

// 对话上下文：随每条消息一并提交。weeks 默认 4。
const context = reactive<ChatContext>({
  resume_text: undefined,
  jd_texts: [],
  target_role: '',
  weeks: 4,
})

// 当前输入框文本。
const input = ref('')

// 思考强度：随 streamChat 以 reasoning_effort 提交，默认 'medium'。
// 6 档：关闭 / 低 / 中 / 高 / 极高 / 最高（中英关键词并列，便于对照模型档位）。
const reasoningEffort = ref<ReasoningEffort>('medium')
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

// E3 人设引擎（B5：单人设 + 语气滑块）：语气强度 0=最温柔…100=最严格，随对话以 context.tone 提交。
const TONE_KEY = 'op.tone'
function readTone(): number {
  try {
    const v = Number(localStorage.getItem(TONE_KEY))
    return Number.isFinite(v) && v >= 0 && v <= 100 ? v : 50
  } catch {
    return 50
  }
}
const tone = ref<number>(readTone())
watch(tone, (v) => {
  try {
    localStorage.setItem(TONE_KEY, String(v))
  } catch {
    /* 隐私模式：忽略持久化失败 */
  }
})
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
  if (streaming.value) return
  e.preventDefault()
  tone.value = clampTone(tone.value + (e.deltaY < 0 ? TONE_STEP : -TONE_STEP))
}

// 高层阶段提示（onStatus 的兜底）——显示在输入区上方的细条。
// 注意：run_analysis 运行期间的子步骤优先写入对应 tool 块的 status；
// 仅在找不到进行中的工具块时，才退化为这里的顶部细条。
const statusLine = ref('')

// 流式进行中标记与中止控制器。
const streaming = ref(false)
let abortController: AbortController | null = null

// ---------- 会话自动保存 ----------
// 当前会话在后端的 id：null 表示尚未保存（新会话）；
// 每轮助手回复结束后自动 upsert，并用返回 id 回填，实现「后续轮次更新同一会话」。
const conversationId = ref<number | null>(null)

// 最近一次匹配分析的 id（来自 report 事件）。随请求 context 回传，
// 供第二步 generate_plan 跨轮定位本次匹配分析。
const currentRunId = ref<number | null>(null)

// ---------- 本会话 token 用量累计 ----------
// 每轮 SSE usage 事件累加到此（input_hit/input_miss/output/total）；
// 续聊加载历史会话时从各轮 usage 重算。供「全链路统一口径」展示本会话累计。
const sessionUsage = ref<TurnUsage>({ input_hit: 0, input_miss: 0, output: 0, total: 0 })

// 把一轮 usage 累加进累计值（纯函数，便于 reduce 重算历史）。
function addUsage(acc: TurnUsage, e: TurnUsage): TurnUsage {
  const input_hit = acc.input_hit + (e.input_hit || 0)
  const input_miss = acc.input_miss + (e.input_miss || 0)
  const output = acc.output + (e.output || 0)
  return { input_hit, input_miss, output, total: input_hit + input_miss + output }
}

// token 数 k 缩写：<1000 原样；≥1000 显示「x.xk」（去掉多余 0）。
function fmtTokens(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  if (v < 1000) return String(v)
  const k = v / 1000
  return `${k >= 100 ? Math.round(k) : Number(k.toFixed(1))}k`
}

// 本会话累计是否有数据（决定是否展示累计小字）。
const hasSessionUsage = computed(() => (sessionUsage.value.total ?? 0) > 0)

// 路由：读取 query.c 以支持「历史续聊」（进入 /?c=<id> 加载该会话续聊）。
const route = useRoute()
const router = useRouter()
// 正在加载历史会话的标记：避免加载期间触发自动保存等副作用。
const loadingConversation = ref(false)

// ---------- DOM 引用 ----------
const scrollRef = ref<HTMLElement | null>(null) // 左栏消息滚动容器（智能滚动只作用于它）
const fileInput = ref<HTMLInputElement | null>(null) // 隐藏的 PDF 文件框
const textareaRef = ref<HTMLTextAreaElement | null>(null) // 输入框
const reportPanelRef = ref<HTMLElement | null>(null) // 右侧报告面板滚动容器（点击 chip 时滚到顶并高亮）

// ---------- 派生状态 ----------
// 是否已存在「可分析的素材」：有简历或至少一条 JD。
const hasAttachments = computed(
  () =>
    Boolean(context.resume_text && context.resume_text.trim()) ||
    (context.jd_texts?.length ?? 0) > 0,
)

// 是否展示空状态欢迎语：尚无任何对话消息。
const showWelcome = computed(() => turns.length === 0)

// ---------- 报告侧边面板 ----------
// 最新报告：遍历所有 turns，取「最后一个」report block（{analysis_run_id, result}）；无则 null。
// 右侧面板只展示这一份最新报告（历史报告在消息流里以紧凑引用 chip 呈现）。
const latestReport = computed<{ analysis_run_id: number; result: AnalysisResult } | null>(
  () => {
    for (let ti = turns.length - 1; ti >= 0; ti--) {
      const t = turns[ti]
      if (t.role !== 'assistant') continue
      for (let bi = t.blocks.length - 1; bi >= 0; bi--) {
        const b = t.blocks[bi]
        if (b.kind === 'report') {
          return { analysis_run_id: b.analysis_run_id, result: b.result }
        }
      }
    }
    return null
  },
)

// 报告侧栏开合：默认展开。隐藏后右栏消失、聊天区占满宽度，
// 并在角落显示「📊 报告」悬浮角标供重新展开。
const reportPanelOpen = ref(true)

// 新报告到达（latestReport 由「无 / 旧 id」变为「有值且 id 变化」）时自动展开，
// 确保用户总能看到最新摘要；用 analysis_run_id 作为变化键避免内容更新时误触发。
watch(
  () => latestReport.value?.analysis_run_id ?? null,
  (id, prev) => {
    if (id != null && id !== prev) reportPanelOpen.value = true
  },
)

// 隐藏报告面板（面板内「隐藏」按钮）。隐藏后经左侧边栏入口重新展开（见 focusReportPanel）。
function hideReportPanel(): void {
  reportPanelOpen.value = false
}

// 跳转到完整报告页（/result/:id，全展开）。
// 携带 ?from=<当前会话 id>，让完整报告页左上角「返回」回到本对话（续聊态），而非新建空对话。
async function goToFullReport(): Promise<void> {
  const id = latestReport.value?.analysis_run_id
  if (id == null) return
  // 确保当前会话已落库拿到 id（通常每轮结束已自动保存，这里兜底）。
  if (conversationId.value == null) await persistConversation()
  const query = conversationId.value != null ? { from: String(conversationId.value) } : undefined
  void router.push({ name: 'result', params: { id }, query })
}

// ---------- 学习方案（最终主产出） ----------
// 最新报告里的学习路线（周计划）；为空表示尚未进入第二步生成计划。
const latestRoadmap = computed<WeekItem[]>(() => {
  const r = latestReport.value?.result.roadmap
  return Array.isArray(r) ? [...r].sort((a, b) => a.week - b.week) : []
})
// 是否已生成学习方案（有非空周计划）——决定侧栏以「学习方案」还是「匹配分析」为主角。
const hasPlan = computed(() => latestRoadmap.value.length > 0)
// 侧栏学习方案预览：取前 3 周（周号 + 该周聚焦技能前 3 项）。
const planPreview = computed(() =>
  latestRoadmap.value.slice(0, 3).map((w) => ({
    week: w.week,
    focus: (w.focus_skills ?? []).slice(0, 3),
  })),
)
// 主按钮文案：已出方案 → 查看完整学习方案；仅匹配分析 → 查看完整报告。
const fullReportCtaLabel = computed(() =>
  hasPlan.value ? '查看完整学习方案' : '查看完整报告',
)

// 点击报告引用 chip 时，让右侧面板滚到顶并短暂高亮（提示「报告在这里」）。
const reportHighlight = ref(false)
let reportHighlightTimer: ReturnType<typeof setTimeout> | undefined

// 发送按钮是否可用：流式中不可发；否则需有文本或有新素材。
const canSend = computed(
  () => !streaming.value && (input.value.trim().length > 0 || hasAttachments.value),
)

// 周数下拉选项 1~12。
const weekOptions = Array.from({ length: 12 }, (_, i) => i + 1)

// ---------- 智能滚动 ----------
// 贴底判定阈值：滚动位置距底部 <= 此像素数视为「贴底」。
const BOTTOM_THRESHOLD = 80

// 是否处于（或贴近）底部。初始为真：空会话/首次进入应跟随最新内容。
const atBottom = ref(true)
// 流式中有新内容、但用户已上滑离开底部 → 用于「回到底部」按钮上的提示点。
const hasUnreadBelow = ref(false)

// 计算当前滚动容器是否贴底。
function computeAtBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD
}

// 滚动事件：实时维护 atBottom；一旦回到底部即清除未读提示。
function onScroll(): void {
  const el = scrollRef.value
  if (!el) return
  atBottom.value = computeAtBottom(el)
  if (atBottom.value) hasUnreadBelow.value = false
}

// 滚到最底；用 nextTick 等待 DOM 更新。force=true 时无视当前位置强制贴底。
async function scrollToBottom(force = false): Promise<void> {
  if (!force && !atBottom.value) return
  await nextTick()
  const el = scrollRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  atBottom.value = true
  hasUnreadBelow.value = false
}

// 点击「回到底部」浮动按钮：强制贴底并清除未读提示。
function jumpToBottom(): void {
  void scrollToBottom(true)
}

// 流式期间内容持续增长，监听消息变化做「智能贴底」。
// 追踪：消息条数、各助手消息的 blocks 数量、末块的文本长度 / 工具状态、流式标记，
// 以覆盖「新增气泡、增量文本、工具活动、报告到达」等所有会改变高度的情形。
// 行为：仅当 atBottom 为真时才自动贴底；用户上滑离开底部后不再强制拉回，
// 此时若仍在流式中则点亮「回到底部」按钮的未读提示点。
watch(
  () =>
    turns
      .map((t) => {
        if (t.role !== 'assistant') return 'u'
        const last = t.blocks[t.blocks.length - 1]
        let tail = ''
        if (last) {
          if (last.kind === 'text' || last.kind === 'reasoning') {
            tail = `${last.kind}:${last.text.length}`
          } else if (last.kind === 'tool') {
            tail = `tool:${last.ok === undefined ? 0 : 1}:${last.steps?.length ?? 0}:${last.status?.length ?? 0}`
          } else {
            tail = 'report'
          }
        }
        return `a:${t.blocks.length}:${tail}:${t.streaming ? 1 : 0}:${t.error ? 1 : 0}`
      })
      .join('|'),
  () => {
    if (atBottom.value) {
      void scrollToBottom()
    } else if (streaming.value) {
      // 用户在上方查看历史，下方有新内容到达 → 提示有新内容
      hasUnreadBelow.value = true
    }
  },
)

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
  context.resume_text = text
  pasteText.value = ''
  pasteOpen.value = false
  flashHint('已将粘贴内容设为简历')
}

// 把内联文本作为一条 JD 追加。
function applyPasteAsJd(): void {
  const text = pasteText.value.trim()
  if (!text) return
  if (!context.jd_texts) context.jd_texts = []
  context.jd_texts.push(text)
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
  context.jd_texts?.splice(index, 1)
  if ((context.jd_texts?.length ?? 0) === 0) jdManagerOpen.value = false
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
  if (!context.jd_texts) context.jd_texts = []
  context.jd_texts.push(...list)
  flashHint(`已添加 ${list.length} 条 JD`)
}

// 把已添加的某条 JD「存入 JD 库」：标题取前 20 字（去空白），空则「未命名 JD」。
const savingJdIndex = ref<number | null>(null)
async function saveJdToLibrary(index: number): Promise<void> {
  if (savingJdIndex.value !== null) return
  const content = context.jd_texts?.[index]?.trim()
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
  context.resume_text = undefined
}

// —— 分析设置（目标岗位 / 周数）开合 ——
const settingsOpen = ref(false)
function toggleSettings(): void {
  settingsOpen.value = !settingsOpen.value
}

// —— 模型设置（自定义大语言模型 BYO LLM）开合与拉取态 ——
// 面板里直接 v-model 绑 llmConfig（全局单例，localStorage 持久化由 llmConfig.ts 负责）。
const modelSettingsOpen = ref(false)
// 从所填端点拉取到的可用模型列表（供三档输入框的 datalist 下拉；拉不到时仍可手输）。
const modelList = ref<string[]>([])
// 拉取状态机与状态文案。
const modelFetchState = ref<'idle' | 'loading' | 'ok' | 'error'>('idle')
const modelFetchMsg = ref('')
// Provider 协议选项（与后端 _eff_provider 的两类客户端对应）。
const providerOptions = [
  { value: 'openai', label: 'OpenAI 协议' },
  { value: 'anthropic', label: 'Anthropic 协议' },
]
function toggleModelSettings(): void {
  modelSettingsOpen.value = !modelSettingsOpen.value
}
// 刷新模型列表（顺带是连通性测试）：成功填 modelList，失败仍允许手输。
async function refreshModels(): Promise<void> {
  modelFetchState.value = 'loading'
  const res = await fetchLLMModels(llmConfig.value)
  if (res.ok) {
    modelList.value = res.models
    modelFetchState.value = 'ok'
    modelFetchMsg.value = `已连接，${res.models.length} 个模型`
  } else {
    modelFetchState.value = 'error'
    modelFetchMsg.value = res.error || '拉取失败，可手输'
  }
}

// ---------- PDF 上传 ----------
const uploading = ref(false)

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

// 统一的简历文件处理：校验 PDF → 上传解析 → 写入 context.resume_text。
// 文件框选择与拖拽放入共用。
async function ingestResumeFile(file: File): Promise<void> {
  if (uploading.value) return
  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    flashHint('目前仅支持 PDF 简历，其它格式请粘贴文本', true)
    return
  }
  uploading.value = true
  try {
    const resume = await uploadResume(file)
    context.resume_text = resume.raw_text
    flashHint(`已添加简历「${file.name}」`)
  } catch (err) {
    flashHint(err instanceof Error ? err.message : '简历解析失败，请重试', true)
  } finally {
    uploading.value = false
  }
}

// ---------- 拖拽上传 ----------
// 拖动文件到 composer 时，输入区扩大并提示「松开以上传简历」。
// 用计数器避免子元素 dragenter/dragleave 造成的闪烁。
const dragOver = ref(false)
let dragDepth = 0

// 仅对「文件」拖拽响应（忽略选中文本等拖拽）。
function isFileDrag(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

function onDragEnter(e: DragEvent): void {
  if (!isFileDrag(e)) return
  e.preventDefault()
  dragDepth += 1
  dragOver.value = true
}

function onDragOver(e: DragEvent): void {
  if (!isFileDrag(e)) return
  e.preventDefault() // 必须阻止默认才能触发 drop
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(e: DragEvent): void {
  if (!isFileDrag(e)) return
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragOver.value = false
  }
}

async function onDrop(e: DragEvent): Promise<void> {
  if (!isFileDrag(e)) return
  e.preventDefault()
  dragDepth = 0
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) await ingestResumeFile(file)
}

// ---------- 轻量浮层提示 ----------
const hint = ref('')
const hintError = ref(false)
let hintTimer: ReturnType<typeof setTimeout> | undefined

// 短暂展示一条操作反馈，自动消失。
function flashHint(message: string, isError = false): void {
  hint.value = message
  hintError.value = isError
  if (hintTimer) clearTimeout(hintTimer)
  hintTimer = setTimeout(() => {
    hint.value = ''
  }, 2600)
}

// ===================================================================
//  组合输入区：视觉融合 + 失焦折叠为一行
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
    (context.resume_text && context.resume_text.trim() ? 1 : 0) +
    (context.jd_texts?.length ?? 0),
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

// ===================================================================
//  发送与流式处理
// ===================================================================

// 把一条助手消息的所有 text 块拼接为发给后端的纯文本（忽略思考/工具/报告）。
function assistantPlainText(t: AssistantTurn): string {
  return t.blocks
    .filter((b): b is Extract<AssistantBlock, { kind: 'text' }> => b.kind === 'text')
    .map((b) => b.text)
    .join('')
}

// 把渲染用消息投影为发给后端的 { role, content }。
// user 取其文本；assistant 取所有 text 块拼接。
function toPayloadMessages(list: ChatTurn[]): ChatMessage[] {
  return list.map((t) =>
    t.role === 'user'
      ? { role: 'user', content: t.text }
      : { role: 'assistant', content: assistantPlainText(t) },
  )
}

// 当前 context 的纯净快照（去掉空字段，避免回传无意义数据）。
function snapshotContext(): ChatContext {
  const ctx: ChatContext = { weeks: context.weeks ?? 4 }
  if (context.resume_text && context.resume_text.trim()) {
    ctx.resume_text = context.resume_text
  }
  if (context.jd_texts && context.jd_texts.length) {
    ctx.jd_texts = [...context.jd_texts]
  }
  if (context.target_role && context.target_role.trim()) {
    ctx.target_role = context.target_role.trim()
  }
  if (currentRunId.value != null) {
    ctx.analysis_run_id = currentRunId.value
  }
  ctx.tone = tone.value // E3：随对话提交语气强度
  return ctx
}

// 当前 context 的「可持久化快照」（随会话存盘，供历史续聊恢复上下文）。
// 与 snapshotContext 同步：去掉空字段，analysis_run_id 取 currentRunId。
function snapshotPersistContext(): ChatPersistContext {
  const ctx: ChatPersistContext = { weeks: context.weeks ?? 4 }
  if (context.resume_text && context.resume_text.trim()) {
    ctx.resume_text = context.resume_text
  }
  if (context.jd_texts && context.jd_texts.length) {
    ctx.jd_texts = [...context.jd_texts]
  }
  if (context.target_role && context.target_role.trim()) {
    ctx.target_role = context.target_role.trim()
  }
  if (currentRunId.value != null) {
    ctx.analysis_run_id = currentRunId.value
  }
  ctx.tone = tone.value // E3：语气强度随会话存盘，续聊恢复
  return ctx
}

// 点击发送：组装用户消息与助手占位，发起流式对话。
async function send(): Promise<void> {
  if (streaming.value) return

  const raw = input.value.trim()
  // 文本为空但已有新素材：自动补一条引导文本（如「刚传完简历直接开始分析」）。
  if (!raw && !hasAttachments.value) return
  const userText = raw || '请基于我已提供的简历和 JD 开始分析。'

  // 1) 追加用户消息
  turns.push({ role: 'user', text: userText })
  input.value = ''
  resetTextareaHeight()
  // 用户主动发送：强制贴底并复位 atBottom，确保看到自己刚发出的消息与后续回复
  void scrollToBottom(true)

  // 2) 计算本轮要发送的历史（含刚加入的用户消息），用于请求与重试
  const requestMessages = toPayloadMessages(turns)

  // 3) 追加助手占位消息并开始流式
  const assistant = reactive<AssistantTurn>({
    role: 'assistant',
    blocks: [],
    error: undefined,
    streaming: true,
    requestMessages,
    reasoningOpen: {},
    effort: undefined,
    noThinking: false,
  })
  turns.push(assistant)

  await runChat(assistant, requestMessages)
}

// ---------- block 操作小工具 ----------
// 取末块。
function lastBlock(a: AssistantTurn): AssistantBlock | undefined {
  return a.blocks[a.blocks.length - 1]
}

// 真正执行一轮 SSE：handlers 仅更新传入的助手消息对象，与渲染解耦。
async function runChat(
  assistant: AssistantTurn,
  requestMessages: ChatMessage[],
): Promise<void> {
  // 重置该条消息的可变状态（用于重试场景复用同一对象）
  assistant.blocks = []
  assistant.error = undefined
  assistant.streaming = true
  assistant.reasoningOpen = {}
  assistant.noThinking = false
  // 记录发起本轮所用的思考强度（结束时据此判断「应有思考却无思考」；
  // 重试时会按当前选择刷新，符合「发起该轮时所用强度」语义）。
  const turnEffort = reasoningEffort.value
  assistant.effort = turnEffort

  streaming.value = true
  statusLine.value = ''
  abortController = new AbortController()

  await streamChat(
    {
      messages: requestMessages,
      context: snapshotContext(),
      reasoning_effort: turnEffort,
      // 自定义大语言模型覆盖（六字段全空则为 undefined，回退后端 .env）。
      llm_override: effectiveOverride(),
      // 当前本地时间（可读字符串）——让 AI 知道“现在”，避免检索旧年份信息。
      client_time: new Date().toLocaleString('zh-CN', { hour12: false }),
    },
    {
      // 思考增量：末块是 reasoning 则追加，否则新开一个 reasoning 块（流式默认展开）
      onReasoning: (e) => {
        const last = lastBlock(assistant)
        if (last && last.kind === 'reasoning') {
          last.text += e.text
        } else {
          assistant.blocks.push({ kind: 'reasoning', text: e.text })
          assistant.reasoningOpen[assistant.blocks.length - 1] = true
        }
      },
      // 增量文本：末块是 text 则追加，否则新开一个 text 块
      onDelta: (e) => {
        const last = lastBlock(assistant)
        if (last && last.kind === 'text') {
          last.text += e.text
        } else {
          assistant.blocks.push({ kind: 'text', text: e.text })
        }
      },
      // 工具调用 → 追加一个「进行中」工具块（steps 初始化为空，承载过程日志）
      onToolCall: (e) => {
        assistant.blocks.push({
          kind: 'tool',
          id: e.id,
          name: e.name,
          label: e.label,
          steps: [],
          resultsOpen: false,
        })
      },
      // 阶段/子进度：把 message【追加】到「最近一个未完成的工具块」的 steps 过程日志，
      // 并把 status 记为最后一条（展示以 steps 列表为准）；
      // 找不到进行中的工具块才退化为顶部细条。
      onStatus: (e) => {
        const pending = findPendingTool(assistant)
        if (pending) {
          if (!pending.steps) pending.steps = []
          pending.steps.push(e.message)
          pending.status = e.message
          statusLine.value = ''
        } else {
          statusLine.value = e.message
        }
      },
      // 工具返回 → 按 id 更新对应块（标记完成 + 替换为结果摘要 + 清空进行中单行；
      // steps 过程日志保留，供用户回看分析过程）
      onToolResult: (e) => {
        const t = findToolById(assistant, e.id)
        if (t) {
          t.ok = e.ok
          if (e.label) t.label = e.label
          t.status = undefined
        } else {
          // 兜底：未见过 tool_call 也补一个已完成块，避免结果丢失
          assistant.blocks.push({
            kind: 'tool',
            id: e.id,
            name: e.name,
            label: e.label,
            ok: e.ok,
          })
        }
      },
      // 联网搜索结果详情 → 挂到对应 web_search 工具块（默认折叠，用户可展开查看）
      onSearchResults: (e) => {
        const t = findToolById(assistant, e.id)
        if (t) {
          t.query = e.query
          t.results = e.results
        }
      },
      // 结构化报告 → 追加报告块，并把对应 run_analysis 工具块的 status 清空
      onReport: (e) => {
        clearAnalysisToolStatus(assistant)
        // 记录最近一次匹配分析 id，供第二步 generate_plan 跨轮使用
        currentRunId.value = e.analysis_run_id
        assistant.blocks.push({
          kind: 'report',
          analysis_run_id: e.analysis_run_id,
          result: e.result,
        })
      },
      // 本轮 token 用量 → 记到该条消息（气泡小字）并累加到本会话累计
      onUsage: (e) => {
        assistant.usage = e
        sessionUsage.value = addUsage(sessionUsage.value, e)
      },
      // 出错 → 记录到该条消息，模板内展示错误条 + 重试
      onError: (e) => {
        assistant.error = e.message || '对话出错，请重试。'
      },
      // 本轮结束
      onDone: () => {
        statusLine.value = ''
      },
    },
    abortController.signal,
  )

  // 流结束（正常 / 中止 / 出错）后统一收尾
  assistant.streaming = false
  streaming.value = false
  statusLine.value = ''
  abortController = null
  // 「无思考」提示：本轮发起时强度非 off，但模型未输出任何 reasoning 块，
  // 且本轮无错误（出错时不提示，避免干扰错误条）。
  assistant.noThinking =
    turnEffort !== 'off' &&
    !assistant.error &&
    !assistant.blocks.some((b) => b.kind === 'reasoning')
  // 兜底：若本轮既无任何内容、也无「无思考」提示（如 off 档且模型零输出），
  // 补一条占位文本，确保气泡仍可见、消息不至于凭空消失。
  if (!assistant.error && !assistant.noThinking && assistant.blocks.length === 0) {
    assistant.blocks.push({ kind: 'text', text: '（本轮无输出）' })
  }
  // 本轮结束：自动折叠所有思考块（用户仍可手动展开回看）
  collapseAllReasoning(assistant)
  // 收尾贴底：仅当用户仍在底部时跟随（上滑查看历史则不强拉回）
  void scrollToBottom()
  // 本轮结束后自动保存会话（不阻塞、失败仅告警）
  void persistConversation()
}

// ===================================================================
//  会话自动保存
// ===================================================================

// 把渲染用 turns 序列化为可持久化子集（丢弃 streaming / reasoningOpen /
// requestMessages / effort 等瞬态字段；assistant 仅留 blocks/noThinking/error，
// user 仅留 text）。block 结构与 AssistantBlock / PersistedBlock 严格一致。
function serializeTurns(list: ChatTurn[]): PersistedTurn[] {
  return list.map((t): PersistedTurn => {
    if (t.role === 'user') {
      return { role: 'user', text: t.text }
    }
    const blocks: PersistedBlock[] = t.blocks.map((b) => {
      switch (b.kind) {
        case 'text':
          return { kind: 'text', text: b.text }
        case 'reasoning':
          return { kind: 'reasoning', text: b.text }
        case 'tool':
          return {
            kind: 'tool',
            id: b.id,
            name: b.name,
            label: b.label,
            ok: b.ok,
            status: b.status,
            steps: b.steps,
            query: b.query,
            results: b.results,
          }
        case 'report':
          return {
            kind: 'report',
            analysis_run_id: b.analysis_run_id,
            result: b.result,
          }
      }
    })
    const turn: PersistedTurn = { role: 'assistant', blocks }
    if (t.noThinking) turn.noThinking = true
    if (t.error) turn.error = t.error
    if (t.usage) turn.usage = t.usage // 本轮 token 用量随会话存盘
    return turn
  })
}

// 把持久化的 PersistedTurn[] 反序列化为内部渲染用 ChatTurn[]。
// user → { role, text }；assistant → { role, blocks, noThinking, error, streaming:false, reasoningOpen:{} }。
// blocks 结构与 PersistedBlock / AssistantBlock 一致，逐块映射即可无损还原。
function deserializeTurns(list: PersistedTurn[]): ChatTurn[] {
  return list.map((t): ChatTurn => {
    if (t.role === 'user') {
      return { role: 'user', text: t.text }
    }
    const blocks: AssistantBlock[] = t.blocks.map((b) => {
      switch (b.kind) {
        case 'text':
          return { kind: 'text', text: b.text }
        case 'reasoning':
          return { kind: 'reasoning', text: b.text }
        case 'tool':
          return {
            kind: 'tool',
            id: b.id,
            name: b.name,
            label: b.label,
            ok: b.ok,
            status: b.status,
            steps: b.steps,
            query: b.query,
            results: b.results,
            // 搜索结果折叠态为瞬态：还原时统一以收起态呈现（默认折叠）
            resultsOpen: false,
          }
        case 'report':
          return {
            kind: 'report',
            analysis_run_id: b.analysis_run_id,
            result: b.result,
          }
      }
    })
    return {
      role: 'assistant',
      blocks,
      error: t.error,
      streaming: false,
      // 历史回合不保留瞬态的展开态，统一以收起态还原（用户可手动展开回看）
      reasoningOpen: {},
      noThinking: t.noThinking,
      usage: t.usage, // 还原本轮 token 用量（气泡小字 + 会话累计重算）
    }
  })
}

// 从持久化 turns 中取「最后一个 report 块」的 analysis_run_id（没有则 null）。
// 供续聊时恢复 currentRunId，让第二步 generate_plan 仍能跨轮定位本次匹配分析。
function lastRunIdFromTurns(list: PersistedTurn[]): number | null {
  for (let ti = list.length - 1; ti >= 0; ti--) {
    const t = list[ti]
    if (t.role !== 'assistant') continue
    for (let bi = t.blocks.length - 1; bi >= 0; bi--) {
      const b = t.blocks[bi]
      if (b.kind === 'report') return b.analysis_run_id
    }
  }
  return null
}

// 加载某段已存会话用于「续聊」：拉取详情 → 反序列化 turns → 恢复 context 与
// conversationId / currentRunId → 滚到底部。失败给出错误提示并回退为新对话。
// 注意：加载期间置位 loadingConversation，避免清空动作把会话洗成空白后被误保存。
async function loadConversation(id: number): Promise<void> {
  if (!Number.isFinite(id) || id <= 0) return
  loadingConversation.value = true
  try {
    const detail = await getConversation(id)
    // 还原对话消息
    const restored = deserializeTurns(detail.turns)
    turns.splice(0, turns.length, ...restored)
    // 从各轮 usage 重算本会话 token 累计（续聊恢复全链路口径）
    sessionUsage.value = restored.reduce<TurnUsage>(
      (acc, t) => (t.role === 'assistant' && t.usage ? addUsage(acc, t.usage) : acc),
      { input_hit: 0, input_miss: 0, output: 0, total: 0 },
    )
    // 还原续聊上下文（简历 / JD / 目标岗位 / 周数）
    const ctx = detail.context ?? {}
    context.resume_text =
      ctx.resume_text && ctx.resume_text.trim() ? ctx.resume_text : undefined
    context.jd_texts = Array.isArray(ctx.jd_texts) ? [...ctx.jd_texts] : []
    context.target_role = ctx.target_role ?? ''
    context.weeks = ctx.weeks ?? 4
    // E3：恢复该会话存盘的语气强度（无则保持当前/默认）
    if (typeof ctx.tone === 'number' && ctx.tone >= 0 && ctx.tone <= 100) {
      tone.value = ctx.tone
    }
    // 绑定到同一会话，后续轮次保存回此 id
    conversationId.value = detail.id
    // 恢复最近一次匹配分析 id：优先取 turns 中最后一个 report 块，
    // 兜底回退到持久化 context.analysis_run_id（两者通常一致）。
    currentRunId.value = lastRunIdFromTurns(detail.turns) ?? ctx.analysis_run_id ?? null
    // 进入续聊：滚到底部，用户可直接继续对话
    atBottom.value = true
    hasUnreadBelow.value = false
    void scrollToBottom(true)
    // 续聊会话载入完成，聚焦输入框便于继续对话
    autoFocusInput()
  } catch (err) {
    // 加载失败：提示并回退为一段空白新对话（去掉 query.c，避免反复重试）
    flashHint(err instanceof Error ? err.message : '加载历史会话失败，已切换为新对话', true)
    turns.splice(0, turns.length)
    conversationId.value = null
    currentRunId.value = null
    sessionUsage.value = { input_hit: 0, input_miss: 0, output: 0, total: 0 }
    if (route.query.c != null) void router.replace('/')
  } finally {
    loadingConversation.value = false
  }
}

// 监听路由 query.c：进入或其变化为某会话 id 时加载续聊；为空时不动作
// （避免与「新对话」清空冲突——清空由 newConversation 主动完成）。
// immediate：首次进入 /?c=<id> 即触发加载。
watch(
  () => route.query.c,
  (raw) => {
    const id = Number(Array.isArray(raw) ? raw[0] : raw)
    if (!raw || !Number.isFinite(id) || id <= 0) return
    // 已是该会话则无需重复加载（如自身保存后路由未变的情形）
    if (conversationId.value === id && turns.length > 0) return
    void loadConversation(id)
  },
  { immediate: true },
)

// 取首条 user 文本截断到约 30 字作为标题；无则「未命名对话」。
function deriveTitle(list: ChatTurn[]): string {
  const firstUser = list.find((t): t is UserTurn => t.role === 'user')
  const text = firstUser?.text.trim() ?? ''
  if (!text) return '未命名对话'
  return text.length > 30 ? `${text.slice(0, 30)}…` : text
}

// upsert 当前会话：需至少 1 条 user 消息；用返回 id 回填 conversationId。
// 失败仅 console 警告，不打扰用户。
async function persistConversation(): Promise<void> {
  // 历史会话加载中：跳过保存，避免与加载中的中间态竞争写回
  if (loadingConversation.value) return
  if (!turns.some((t) => t.role === 'user')) return
  try {
    const saved = await saveConversation({
      id: conversationId.value,
      title: deriveTitle(turns),
      turns: serializeTurns(turns),
      // 随会话存盘当前上下文快照，供「历史续聊」恢复简历/JD/目标岗位/周数/分析 id
      context: snapshotPersistContext(),
    })
    conversationId.value = saved.id
    // 通知左侧栏刷新「最近会话」列表（新会话/新标题即时出现）
    notifyConversationsChanged()
  } catch (err) {
    console.warn('[会话自动保存失败]', err)
  }
}

// ---------- 新对话 ----------
// 清空当前对话并开始一段全新会话（conversationId 置空 → 下次保存即新建）。
// 同时去掉路由 query.c，避免续聊监听器把刚清空的会话重新加载回来。
function newConversation(): void {
  if (streaming.value) return
  turns.splice(0, turns.length)
  conversationId.value = null
  currentRunId.value = null
  sessionUsage.value = { input_hit: 0, input_miss: 0, output: 0, total: 0 }
  statusLine.value = ''
  atBottom.value = true
  hasUnreadBelow.value = false
  // 当前停留在 /?c=<id> 时，回到干净的 '/'（无 query）开始新对话
  if (route.query.c != null) void router.replace('/')
  // 新对话就绪，聚焦输入框便于立即开始
  autoFocusInput()
}

// 侧边栏「新对话」按钮：通过共享信号触发本视图重置（路由跳转由侧栏负责）。
watch(newChatSignal, () => {
  // 历史会话加载中不重置，避免与加载中态竞争
  if (!loadingConversation.value) newConversation()
})

// 找「最近一个未完成（ok===undefined）的工具块」。
function findPendingTool(
  a: AssistantTurn,
): Extract<AssistantBlock, { kind: 'tool' }> | undefined {
  for (let i = a.blocks.length - 1; i >= 0; i--) {
    const b = a.blocks[i]
    if (b.kind === 'tool' && b.ok === undefined) return b
  }
  return undefined
}

// 按 id 找工具块。
function findToolById(
  a: AssistantTurn,
  id: string,
): Extract<AssistantBlock, { kind: 'tool' }> | undefined {
  for (const b of a.blocks) {
    if (b.kind === 'tool' && b.id === id) return b
  }
  return undefined
}

// 报告到达时，清空对应 run_analysis 工具块仍残留的子步骤文案。
function clearAnalysisToolStatus(a: AssistantTurn): void {
  for (let i = a.blocks.length - 1; i >= 0; i--) {
    const b = a.blocks[i]
    if (b.kind === 'tool' && isAnalysisTool(b.name)) {
      b.status = undefined
      return
    }
  }
}

// 本轮结束后折叠所有思考块。
function collapseAllReasoning(a: AssistantTurn): void {
  a.blocks.forEach((b, idx) => {
    if (b.kind === 'reasoning') a.reasoningOpen[idx] = false
  })
}

// 流式中点击「停止」：中止当前请求。
function stop(): void {
  abortController?.abort()
}

// 编辑某条用户消息：把它放回输入框，并移除它及其之后的所有消息（回复），
// 便于改完重新发送。常用于「不小心回车 → 点停止 → 编辑上一条」。
// 流式进行中不可编辑，请先点「停止」。
function editTurn(index: number): void {
  if (streaming.value) return
  const turn = turns[index]
  if (!turn || turn.role !== 'user') return
  input.value = turn.text
  // 截断：移除该用户消息及其之后的所有消息
  turns.splice(index)
  void nextTick(() => {
    autoGrow()
    textareaRef.value?.focus()
  })
}

// 重试某条出错的助手消息：用其记录的历史快照重新发起。
async function retry(assistant: AssistantTurn): Promise<void> {
  if (streaming.value) return
  const msgs = assistant.requestMessages ?? toPayloadMessages(
    // 兜底：截取到该助手消息之前的全部消息
    turns.slice(0, turns.indexOf(assistant)),
  )
  await runChat(assistant, msgs)
}

// ---------- 输入框：Enter 发送 / Shift+Enter 换行 + 自适应高度 ----------
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

// 随内容增减自适应高度（限制最大高度，超出滚动）。
function autoGrow(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

function resetTextareaHeight(): void {
  const el = textareaRef.value
  if (el) el.style.height = 'auto'
}

// 让输入框获得焦点（聚焦同时会经 composer 的 focusin 展开输入区）。
// 仅宽屏自动聚焦：移动端自动聚焦会立刻弹出软键盘，打扰浏览，故跳过。
function autoFocusInput(): void {
  if (!isWide.value) return
  void nextTick(() => textareaRef.value?.focus())
}

// 页面打开即聚焦输入框，用户可直接开始输入。
onMounted(autoFocusInput)

// 输入内容变化时同步高度。
watch(input, () => {
  void nextTick(autoGrow)
})

// ===================================================================
//  渲染辅助
// ===================================================================
// 是否为「运行分析」类工具（决定是否展示子步骤进度文案）。
function isAnalysisTool(name: string): boolean {
  return name === 'run_analysis' || name === 'analysis' || name === 'analyze'
}

// 依据工具名给一个图标；默认放大镜。
function toolIcon(name: string): string {
  if (name === 'web_search') return '🔍'
  if (isAnalysisTool(name)) return '📊'
  return '🛠'
}

// 切换某个思考块的展开/收起。
function toggleReasoning(a: AssistantTurn, idx: number): void {
  a.reasoningOpen[idx] = !a.reasoningOpen[idx]
}

// 切换某个 web_search 工具块「搜索结果」的展开/收起（默认折叠）。
function toggleSearchResults(block: AssistantBlock): void {
  if (block.kind === 'tool') block.resultsOpen = !block.resultsOpen
}

// 校验搜索结果链接协议：仅放行 http/https，挡掉 javascript:/data: 等危险协议，
// 防止脏数据或中间人注入可执行链接（搜索结果来自外部 Tavily，需视为不可信）。
function isSafeUrl(url: unknown): boolean {
  if (typeof url !== 'string' || !url) return false
  try {
    const p = new URL(url)
    return p.protocol === 'http:' || p.protocol === 'https:'
  } catch {
    return false
  }
}

// 末块是否为「进行中的工具块」（它自身已有 spinner + 过程日志，无需再叠加打字动效）。
function lastBlockIsRunningTool(a: AssistantTurn): boolean {
  const last = a.blocks[a.blocks.length - 1]
  return !!last && last.kind === 'tool' && last.ok === undefined
}

// 是否显示「工作中」动效：流式期间，且当前没有正在转的工具块时常驻。
// 这样在「模型已输出文字、但仍在后台生成工具调用参数」等空窗期也有动效，避免看起来卡死。
function showWorking(a: AssistantTurn): boolean {
  return a.streaming && !lastBlockIsRunningTool(a)
}

// 是否需要渲染气泡容器：有任意 block（非报告）、流式中、出错、或有「无思考」提示。
// 报告块改在右侧面板展示（消息流里仅留引用 chip），故气泡是否出现只看
// 「非报告 block / 流式 / 错误 / 无思考提示」。
function hasBubble(a: AssistantTurn): boolean {
  if (a.streaming || a.error || a.noThinking || a.usage) return true
  return a.blocks.some((b) => b.kind !== 'report')
}

// 点击消息流里的报告引用 chip：让右侧（或窄屏下方）报告面板滚到顶并短暂高亮，
// 帮助用户把视线引导到报告所在处。报告面板仅展示「最新」一份，故此处不按具体 block 定位。
// 若面板当前被隐藏，则先展开（reportPanelOpen=true）再滚动/高亮。
function focusReportPanel(): void {
  // 先确保面板可见（隐藏态下 <aside> 不渲染，需置位后等 DOM 更新才能拿到 ref）
  reportPanelOpen.value = true
  void nextTick(() => {
    const el = reportPanelRef.value
    if (el) {
      // 面板自身滚到顶；并把面板滚入视口（窄屏堆叠在下方时尤为有用）
      el.scrollTop = 0
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
    // 触发一次短暂高亮（重置计时器以支持连续点击）
    reportHighlight.value = false
    void nextTick(() => {
      reportHighlight.value = true
      if (reportHighlightTimer) clearTimeout(reportHighlightTimer)
      reportHighlightTimer = setTimeout(() => {
        reportHighlight.value = false
      }, 1200)
    })
  })
}

// ---------- 与左侧边栏的报告入口协同 ----------
// 报告/学习方案入口已移到 SideNav（取代原右下角悬浮角标，避免与发送按钮重叠）。
// 把「是否有报告 / 面板是否展开 / 是否已出方案」实时同步给侧栏，让其据此显示入口。
watch(
  [() => latestReport.value != null, reportPanelOpen, hasPlan],
  ([avail, open, plan]) => {
    reportNav.available = avail
    reportNav.open = open
    reportNav.hasPlan = plan
  },
  { immediate: true },
)

// 侧栏点击「报告 / 学习方案」入口 → 展开并滚动高亮报告面板（复用 chip 的定位逻辑）。
watch(openReportSignal, () => {
  if (latestReport.value) focusReportPanel()
})

// 离开对话视图时清空入口状态，避免其它视图下侧栏残留报告入口。
onUnmounted(() => {
  reportNav.available = false
})
</script>

<template>
  <div class="chat">
    <!-- 顶部不再有横栏（品牌 / 新对话 / 历史已移入左侧边栏），对话内容不被遮挡 -->

    <!-- ============ 左右两栏外壳 ============
         左栏：消息滚动区 + 浮动回到底部按钮 + 底部 composer（智能滚动只作用于左栏）。
         右栏：报告【紧凑摘要】面板，仅当存在最新报告且面板未隐藏时显示
         （宽屏 sticky；窄屏堆叠到对话下方）。隐藏时聊天区占满宽度。 -->
    <div
      class="chat__main"
      :class="{ 'chat__main--with-report': latestReport && reportPanelOpen }"
    >
      <!-- 左栏 -->
      <div class="chat__left">
    <!-- ============ 消息滚动区 ============ -->
    <div ref="scrollRef" class="chat__scroll" @scroll="onScroll">
      <div class="chat__thread">
        <!-- 空状态：欢迎语 -->
        <div v-if="showWelcome" class="msg msg--assistant">
          <div class="avatar avatar--assistant" aria-hidden="true">OP</div>
          <div class="bubble bubble--assistant welcome">
            <p class="welcome__hello">你好，我是 OfferPilot。</p>
            <p>
              上传简历并添加目标岗位 JD，我来分析匹配度、技能缺口和分周学习路线；
              也可以直接说你想找什么方向，我会先帮你把岗位要求查清楚。
            </p>
            <p class="welcome__tip muted">
              提示：先用下方「上传简历」或「粘贴简历 / 添加 JD」准备素材，
              再发送即可开始分析。
            </p>
          </div>
        </div>

        <!-- 消息列表 -->
        <template v-for="(turn, i) in turns" :key="i">
          <!-- 用户气泡（右）：纯文本，悬停显示「编辑」（流式中禁用，需先停止） -->
          <div v-if="turn.role === 'user'" class="msg msg--user">
            <div class="msg__user-wrap">
              <div class="bubble bubble--user">{{ turn.text }}</div>
              <button
                type="button"
                class="msg-edit"
                :disabled="streaming"
                :title="streaming ? '请先点「停止」再编辑' : '编辑这条消息（会移除其后的回复并放回输入框）'"
                @click="editTurn(i)"
              >
                编辑
              </button>
            </div>
          </div>

          <!-- 助手气泡（左）。显式判定 role 以便类型在该分支内收窄为助手消息 -->
          <div v-else-if="turn.role === 'assistant'" class="msg msg--assistant">
            <div class="avatar avatar--assistant" aria-hidden="true">OP</div>
            <div class="msg__assistant-body">
              <!-- 气泡：按 blocks 顺序交错渲染「思考 / 文本 / 工具」；报告在气泡外全宽渲染 -->
              <div v-if="hasBubble(turn)" class="bubble bubble--assistant">
                <!-- 有序 blocks：渲染顺序即真实发生顺序 -->
                <template v-for="(block, bi) in turn.blocks" :key="bi">
                  <!-- 思考过程：可折叠、弱化、markdown -->
                  <section
                    v-if="block.kind === 'reasoning'"
                    class="reasoning"
                    :class="{ 'reasoning--open': turn.reasoningOpen[bi] }"
                  >
                    <button
                      type="button"
                      class="reasoning__head"
                      :aria-expanded="!!turn.reasoningOpen[bi]"
                      @click="toggleReasoning(turn, bi)"
                    >
                      <span class="reasoning__icon" aria-hidden="true">💭</span>
                      <span class="reasoning__title">思考过程</span>
                      <span
                        class="reasoning__caret"
                        :class="{ open: turn.reasoningOpen[bi] }"
                        aria-hidden="true"
                      >▸</span>
                    </button>
                    <div v-show="turn.reasoningOpen[bi]" class="reasoning__body">
                      <MarkdownText :text="block.text" />
                    </div>
                  </section>

                  <!-- 普通回复：markdown -->
                  <MarkdownText
                    v-else-if="block.kind === 'text'"
                    class="bubble__md"
                    :text="block.text"
                  />

                  <!-- 工具活动：标题行（图标 + 结果摘要 + 完成态标记）+ 过程日志列表。
                       过程日志逐条累积；进行中时最后一行带 spinner，完成后保留全部日志。 -->
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
                        <!-- 进行中且尚无过程日志：标题行兜底 spinner（有日志时 spinner 移至末行） -->
                        <span
                          v-if="block.ok === undefined && !(block.steps && block.steps.length)"
                          class="tool__spinner"
                          aria-hidden="true"
                        />
                        <span v-else-if="block.ok === true" class="tool__check">✓</span>
                        <span v-else-if="block.ok === false" class="tool__cross">✕</span>
                      </span>
                    </div>
                    <!-- 过程日志：每行小字、弱化，缩进于标题行之下；进行中末行带 spinner -->
                    <ul
                      v-if="block.steps && block.steps.length"
                      class="tool__steps"
                    >
                      <li
                        v-for="(step, si) in block.steps"
                        :key="si"
                        class="tool__step"
                        :class="{
                          'tool__step--active':
                            block.ok === undefined &&
                            si === (block.steps?.length ?? 0) - 1,
                        }"
                      >
                        <span
                          v-if="
                            block.ok === undefined &&
                            si === (block.steps?.length ?? 0) - 1
                          "
                          class="tool__step-spinner"
                          aria-hidden="true"
                        />
                        <span v-else class="tool__step-dot" aria-hidden="true">·</span>
                        <span class="tool__step-text">{{ step }}</span>
                      </li>
                    </ul>

                    <!-- 联网搜索结果：默认折叠，点击展开（标题链接 + 摘要） -->
                    <div
                      v-if="
                        block.name === 'web_search' &&
                        block.results &&
                        block.results.length
                      "
                      class="search"
                    >
                      <button
                        type="button"
                        class="search__toggle"
                        :aria-expanded="!!block.resultsOpen"
                        @click="toggleSearchResults(block)"
                      >
                        <span
                          class="search__caret"
                          :class="{ open: block.resultsOpen }"
                          aria-hidden="true"
                        >▸</span>
                        搜索结果 {{ block.results.length }} 条<template v-if="block.query">
                          · “{{ block.query }}”</template>
                      </button>
                      <ul v-show="block.resultsOpen" class="search__list">
                        <li
                          v-for="(r, ri) in block.results"
                          :key="ri"
                          class="search__item"
                        >
                          <a
                            v-if="isSafeUrl(r.url)"
                            class="search__link"
                            :href="r.url"
                            target="_blank"
                            rel="noopener noreferrer"
                          >{{ r.title || r.url }}</a>
                          <span v-else class="search__link search__link--plain">
                            {{ r.title || '（无标题）' }}
                          </span>
                          <p v-if="r.snippet" class="search__snippet">{{ r.snippet }}</p>
                        </li>
                      </ul>
                    </div>
                  </div>
                </template>

                <!-- 工作中动效：流式期间常驻（无正在转的工具块时），覆盖文字已出但仍在后台
                     生成工具参数等空窗期，避免看起来卡死 -->
                <div
                  v-if="showWorking(turn)"
                  class="typing"
                  aria-label="处理中"
                >
                  <span /><span /><span />
                </div>

                <!-- 错误条 + 重试 -->
                <div v-if="turn.error" class="err" role="alert">
                  <span class="err__text">{{ turn.error }}</span>
                  <button
                    type="button"
                    class="btn err__retry"
                    :disabled="streaming"
                    @click="retry(turn)"
                  >
                    重试
                  </button>
                </div>

                <!-- 无思考提示：本轮请求了思考但模型未输出思考过程时的弱化小字 -->
                <p v-if="turn.noThinking" class="no-thinking">
                  （当前模型本轮未输出思考过程）
                </p>

                <!-- 本轮 token 用量小字：输入(命中+未命中)（缓存命中）· 输出。
                     口径与统计页一致：input_hit/input_miss/output，数字 k 缩写。 -->
                <p
                  v-if="turn.usage"
                  class="usage-line"
                  :title="`本轮 token：输入 ${turn.usage.input_hit + turn.usage.input_miss}（缓存命中 ${turn.usage.input_hit}）· 输出 ${turn.usage.output}`"
                >
                  📊 输入 {{ fmtTokens(turn.usage.input_hit + turn.usage.input_miss) }}（缓存
                  {{ fmtTokens(turn.usage.input_hit) }}）· 输出
                  {{ fmtTokens(turn.usage.output) }}
                </p>
              </div>

              <!-- 报告引用 chip：报告改在右侧面板展示，消息流里仅留紧凑引用。
                   点击让报告面板滚到顶并短暂高亮。窄屏文案改「见下方报告面板」。 -->
              <template v-for="(block, bi) in turn.blocks" :key="`r-${bi}`">
                <button
                  v-if="block.kind === 'report'"
                  type="button"
                  class="report-chip"
                  title="跳转到报告面板"
                  @click="focusReportPanel"
                >
                  <span class="report-chip__icon" aria-hidden="true">📊</span>
                  <span class="report-chip__text">
                    匹配报告已生成 ·
                    <span class="report-chip__where report-chip__where--wide">见右侧面板</span>
                    <span class="report-chip__where report-chip__where--narrow">见下方报告面板</span>
                  </span>
                </button>
              </template>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 浮动「回到底部」按钮：仅在用户上滑离开底部时出现 -->
    <button
      v-if="!atBottom"
      type="button"
      class="to-bottom"
      :class="{ 'to-bottom--unread': hasUnreadBelow }"
      title="回到底部"
      @click="jumpToBottom"
    >
      <span class="to-bottom__arrow" aria-hidden="true">↓</span>
      <span class="to-bottom__label">回到底部</span>
      <span v-if="hasUnreadBelow" class="to-bottom__dot" aria-hidden="true" />
    </button>

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

        <!-- 模型设置（自定义大语言模型 BYO LLM）：按会话覆盖后端 .env，配置仅存本地浏览器 -->
        <div v-if="modelSettingsOpen" class="panel settings-panel settings-panel--model">
          <label class="settings-panel__field settings-panel__field--provider">
            <span class="settings-panel__label">协议</span>
            <select v-model="llmConfig.provider" class="field">
              <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </label>
          <label class="settings-panel__field">
            <span class="settings-panel__label">接入点 Base URL</span>
            <input
              v-model="llmConfig.base_url"
              class="field"
              type="text"
              placeholder="留空=官方，如 https://api.deepseek.com/v1"
              autocomplete="off"
            />
          </label>
          <label class="settings-panel__field settings-panel__field--full">
            <span class="settings-panel__label">API Key</span>
            <input
              v-model="llmConfig.api_key"
              class="field"
              type="password"
              placeholder="仅存本地浏览器，可留空"
              autocomplete="off"
            />
            <span class="settings-panel__hint">仅存本地浏览器，不会写入会话记录</span>
          </label>
          <label class="settings-panel__field">
            <span class="settings-panel__label">默认模型</span>
            <input
              v-model="llmConfig.model"
              class="field"
              type="text"
              list="op-model-list"
              placeholder="如 deepseek-v4-pro"
              autocomplete="off"
            />
          </label>
          <label class="settings-panel__field">
            <span class="settings-panel__label">简历模型</span>
            <input
              v-model="llmConfig.model_resume"
              class="field"
              type="text"
              list="op-model-list"
              placeholder="留空＝用默认模型"
              autocomplete="off"
            />
          </label>
          <label class="settings-panel__field">
            <span class="settings-panel__label">JD 模型</span>
            <input
              v-model="llmConfig.model_jd"
              class="field"
              type="text"
              list="op-model-list"
              placeholder="留空＝用默认模型"
              autocomplete="off"
            />
          </label>
          <!-- 三档输入框共享的模型候选列表（原生「下拉 + 手输」二合一） -->
          <datalist id="op-model-list">
            <option v-for="m in modelList" :key="m" :value="m" />
          </datalist>
          <!-- 刷新模型列表（顺带连通性测试）+ 状态提示 -->
          <div class="settings-panel__field settings-panel__field--full model-refresh">
            <button
              type="button"
              class="tool-btn"
              :disabled="modelFetchState === 'loading'"
              @click="refreshModels"
            >
              <span aria-hidden="true">↻</span>
              刷新模型列表
            </button>
            <span
              v-if="modelFetchState === 'loading'"
              class="model-refresh__status"
            >拉取中…</span>
            <span
              v-else-if="modelFetchState === 'ok'"
              class="model-refresh__status model-refresh__status--ok"
            >✓ {{ modelFetchMsg }}</span>
            <span
              v-else-if="modelFetchState === 'error'"
              class="model-refresh__status model-refresh__status--error"
            >✗ {{ modelFetchMsg }}（仍可手输）</span>
          </div>
        </div>

        </template>

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
            @click="stop"
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
            @click="send"
          >
            发送
          </button>
        </div>

        <!-- 工具行（仅展开态渲染）：粘贴 / JD 库 / 设置 / 思考强度 -->
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
    </div>
      </div>
      <!-- /左栏 -->

      <!-- 右栏：报告【紧凑摘要】面板。仅当存在最新报告且面板未隐藏时渲染；
           宽屏 sticky，窄屏（媒体查询）回退为非 sticky 并堆叠到对话下方。
           只展示要点（环形匹配度 + 目标岗位 + 简述），完整内容经「查看完整报告」
           跳转 /result/:id（全展开），不再在此内联整份 AnalysisReport。 -->
      <aside v-if="latestReport && reportPanelOpen" class="chat__right">
        <div
          ref="reportPanelRef"
          class="report-panel"
          :class="{ 'report-panel--flash': reportHighlight }"
        >
          <!-- 顶部标题（已出方案 → 学习方案为主角；否则匹配分析）+ 隐藏按钮 -->
          <header class="report-panel__head">
            <span class="report-panel__title">
              <span class="report-panel__title-icon" aria-hidden="true">{{ hasPlan ? '🎓' : '📊' }}</span>
              {{ hasPlan ? '你的学习方案' : '匹配分析' }}
            </span>
            <button
              type="button"
              class="report-panel__hide"
              title="隐藏侧栏（聊天区占满宽度）"
              @click="hideReportPanel"
            >
              隐藏
            </button>
          </header>

          <!-- ===== 已生成学习方案：以「分周学习路线」为主产出 ===== -->
          <template v-if="hasPlan">
            <div class="plan">
              <p class="plan__lead">
                <span class="plan__weeks">{{ latestRoadmap.length }} 周</span>个性化学习路线<!--
                --><span v-if="latestReport.result.target_role" class="plan__role">
                  · {{ latestReport.result.target_role }}</span>
              </p>
              <ul class="plan__list">
                <li v-for="w in planPreview" :key="w.week" class="plan__week">
                  <span class="plan__week-no">第 {{ w.week }} 周</span>
                  <span class="plan__week-focus">
                    <template v-if="w.focus.length">{{ w.focus.join('、') }}</template>
                    <template v-else>综合复盘 / 模拟面试</template>
                  </span>
                </li>
              </ul>
              <p v-if="latestRoadmap.length > planPreview.length" class="plan__more">
                …共 {{ latestRoadmap.length }} 周完整计划，点下方查看
              </p>
            </div>

            <!-- 保留匹配分析简述，维持「方案依据」的上下文（多行截断，不喧宾夺主） -->
            <p
              v-if="latestReport.result.summary"
              class="report-panel__summary report-panel__summary--compact"
            >
              {{ latestReport.result.summary }}
            </p>

            <!-- 匹配度降为次级一行（环形 mini + 文案） -->
            <div class="report-panel__score-row">
              <ScoreRing :score="latestReport.result.match_score" :size="44" :stroke="5" />
              <span class="report-panel__score-text">岗位匹配度 {{ latestReport.result.match_score }}%</span>
            </div>
          </template>

          <!-- ===== 仅匹配分析：紧凑摘要 + 「下一步生成方案」提示 ===== -->
          <template v-else>
            <div class="report-panel__ring">
              <ScoreRing :score="latestReport.result.match_score" :size="120" />
            </div>
            <p v-if="latestReport.result.target_role" class="report-panel__role">
              <span class="report-panel__role-icon" aria-hidden="true">🎯</span>
              {{ latestReport.result.target_role }}
            </p>
            <p v-if="latestReport.result.summary" class="report-panel__summary">
              {{ latestReport.result.summary }}
            </p>
            <p class="report-panel__next">
              <span aria-hidden="true">💡</span>
              回答上方 AI 的几个问题后，我会据此生成你的<strong>完整分周学习方案</strong>。
            </p>
          </template>

          <!-- 主按钮：文案随是否已出方案切换；均跳转 /result/:id 全展开 -->
          <button type="button" class="report-panel__cta" @click="goToFullReport">
            {{ fullReportCtaLabel }}
            <span class="report-panel__cta-arrow" aria-hidden="true">→</span>
          </button>

          <!-- 已出方案：次级入口跳活计划页（可勾选任务 + 每日打卡），不触碰对话内核 -->
          <RouterLink
            v-if="hasPlan && currentRunId"
            class="report-panel__plan-link"
            :to="`/plan/${currentRunId}`"
          >
            📋 开始执行 / 每日打卡
          </RouterLink>
        </div>
      </aside>
    </div>
    <!-- /左右两栏外壳 -->

    <!-- 报告被隐藏时的重新展开入口已移到左侧边栏（SideNav 的「报告 / 学习方案」），
         统一视觉并避免原右下角悬浮角标与发送按钮重叠。 -->

    <!-- JD 库（自包含模态）：composer 的「JD 库」按钮打开；选条后加入本次分析 -->
    <JdLibrary :open="jdLibraryOpen" @close="closeJdLibrary" @use="onUseSavedJds" />
  </div>
</template>

<style scoped>
/* 对话界面占满主区高度（App.vue 的 .app-main--chat 提供 100dvh 高度上下文）。
   不再减去顶栏——顶栏已移除，品牌/新对话/历史在左侧边栏。 */
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 0 var(--space-5) var(--space-4);
}

/* ---------- 左右两栏外壳 ---------- */
/* 宽屏：左（对话）+ 右（成果面板）横向排列，撑满 .chat 剩余高度；居中限宽。 */
.chat__main {
  flex: 1;
  min-height: 0; /* 允许内部滚动容器在 flex 下正确收缩 */
  display: flex;
  gap: var(--space-5);
  width: 100%;
  max-width: 1180px;
  margin-inline: auto;
  padding-top: var(--space-4);
}

/* 左栏：纵向（滚动区 + composer），作为浮动「回到底部」按钮的定位上下文。 */
.chat__left {
  position: relative;
  flex: 1;
  min-width: 0; /* 防止长内容把左栏撑破 */
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 右栏：报告面板容器。宽屏固定宽度，内部 sticky。 */
.chat__right {
  flex: 0 0 380px;
  min-width: 0;
  /* 与左栏顶部对齐；高度由 sticky 面板自行约束 */
  align-self: stretch;
}

/* 报告【紧凑摘要】面板：sticky 贴顶的卡片，只摆要点（不内滚整份报告）；
   切换报告时短暂高亮。 */
.report-panel {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  /* 高亮过渡：box-shadow 渐隐 */
  transition: box-shadow 0.4s ease;
}

.report-panel--flash {
  box-shadow: 0 0 0 3px var(--brand-soft);
}

/* 顶部小标题行：标题 + 「隐藏」按钮 */
.report-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.report-panel__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
}

.report-panel__title-icon {
  font-size: 0.95em;
  line-height: 1;
}

.report-panel__hide {
  flex-shrink: 0;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    border-color var(--transition),
    color var(--transition),
    background var(--transition);
}

.report-panel__hide:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

/* 环形匹配度：居中摆放 */
.report-panel__ring {
  display: flex;
  justify-content: center;
  padding: var(--space-1) 0;
}

/* 目标岗位 */
.report-panel__role {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.report-panel__role-icon {
  flex-shrink: 0;
  font-size: 0.95em;
  line-height: 1;
}

/* 简述：多行截断（clamp 数行），避免把侧栏撑长 */
.report-panel__summary {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--text-secondary);
  /* 多行省略：最多 5 行 */
  display: -webkit-box;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 学习方案视图下的简述：更紧凑（3 行），作为方案依据的上下文，不抢占主体 */
.report-panel__summary--compact {
  -webkit-line-clamp: 3;
  line-clamp: 3;
  font-size: 0.84rem;
  color: var(--text-muted);
}

/* 「查看完整报告」主按钮 */
.report-panel__cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: var(--space-1);
  padding: 10px 16px;
  border: 1px solid var(--brand);
  border-radius: var(--radius);
  background: var(--brand);
  color: var(--text-on-brand);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition:
    background var(--transition),
    border-color var(--transition),
    transform var(--transition);
}

.report-panel__cta:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.report-panel__cta:active {
  transform: translateY(1px);
}

.report-panel__cta-arrow {
  font-size: 1em;
  line-height: 1;
}

/* 次级入口：跳活计划页（开始执行 / 每日打卡） */
.report-panel__plan-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: var(--space-2);
  padding: 8px 14px;
  border: 1px solid var(--brand-soft);
  border-radius: var(--radius);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.86rem;
  font-weight: 600;
  transition:
    border-color var(--transition),
    color var(--transition);
}

.report-panel__plan-link:hover {
  border-color: var(--brand);
  color: var(--brand);
}

/* ---------- 浮动「回到底部」按钮 ---------- */
.to-bottom {
  position: absolute;
  /* 悬浮在 composer 上方居中偏右 */
  right: 50%;
  bottom: 150px;
  transform: translateX(50%);
  z-index: 5;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 0.82rem;
  font-weight: 600;
  box-shadow: var(--shadow-md);
  transition:
    background var(--transition),
    border-color var(--transition),
    color var(--transition);
}

.to-bottom:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--brand-soft);
}

.to-bottom--unread {
  border-color: var(--brand);
  color: var(--brand);
}

.to-bottom__arrow {
  font-size: 0.95rem;
  line-height: 1;
}

/* 流式中下方有新内容、且不在底部：右上角提示点 */
.to-bottom__dot {
  position: absolute;
  top: -3px;
  right: -3px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--brand);
  border: 2px solid var(--surface);
  animation: chat-pulse 1.4s ease-in-out infinite;
}

/* ---------- 消息滚动区 ---------- */
.chat__scroll {
  flex: 1;
  overflow-y: auto;
  /* 给底部 composer 让出呼吸空间，内容不贴边 */
  padding-bottom: var(--space-4);
  scrollbar-width: thin;
}

.chat__thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding-top: var(--space-2);
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

/* 用户消息：气泡 + 悬停显示的「编辑」按钮，整体右对齐纵向堆叠 */
.msg__user-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  min-width: 0;
}

.msg-edit {
  opacity: 0;
  padding: 2px 8px;
  font-size: 0.78rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition:
    opacity 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease;
}

/* 悬停消息或聚焦按钮时显示；触屏无悬停时也可通过 Tab 聚焦 */
.msg--user:hover .msg-edit,
.msg-edit:focus-visible {
  opacity: 1;
}

.msg-edit:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand);
}

.msg-edit:disabled {
  cursor: not-allowed;
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
  /* 块之间留间距：思考 / 文本 / 工具按顺序纵向排列 */
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* markdown 回复块：去掉 MarkdownText 自身的外边距塌陷影响，由父级 gap 控制间距 */
.bubble__md {
  color: var(--text);
}

/* 欢迎语 */
.welcome {
  gap: var(--space-2);
}

.welcome__hello {
  font-weight: 650;
  color: var(--text);
}

.welcome p {
  color: var(--text-secondary);
}

.welcome__tip {
  margin-top: var(--space-1);
  font-size: 0.85rem;
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
  /* 思考内容整体弱化：浅色、小字，与正式回复区分 */
  color: var(--text-muted);
  font-size: 0.86rem;
}

/* 缩小思考区内 markdown 的字号，进一步弱化 */
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
  /* 缩进对齐到标题文字（图标约 1em + gap） */
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

/* 进行中的最后一行：略微强调，并轻微呼吸 */
.tool__step--active {
  color: var(--text-secondary);
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

/* 末行进行中的小 spinner */
.tool__step-spinner {
  flex-shrink: 0;
  align-self: center;
  width: 10px;
  height: 10px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: chat-spin 0.7s linear infinite;
}

.tool__check {
  color: var(--success);
  font-weight: 700;
}

.tool__cross {
  color: var(--danger);
  font-weight: 700;
}

.tool__spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: chat-spin 0.7s linear infinite;
}

/* ---------- 打字指示 ---------- */
.typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 0;
}

.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
  opacity: 0.5;
  animation: chat-bounce 1.2s infinite ease-in-out;
}

.typing span:nth-child(2) {
  animation-delay: 0.15s;
}

.typing span:nth-child(3) {
  animation-delay: 0.3s;
}

/* ---------- 错误条 ---------- */
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

.err__retry {
  flex-shrink: 0;
  padding: 5px 14px;
  font-size: 0.85rem;
}

/* ---------- 无思考提示（很弱化的小字） ---------- */
.no-thinking {
  margin: 0;
  font-size: 0.76rem;
  color: var(--text-muted);
  opacity: 0.7;
  font-style: italic;
}

/* 本轮 token 用量小字：弱化、与气泡其余内容拉开一点距离 */
.usage-line {
  margin: 6px 0 0;
  font-size: 0.74rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}

/* ---------- 报告引用 chip（消息流内，点击跳转右侧/下方报告面板） ---------- */
.report-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start; /* 不撑满整行 */
  max-width: 100%;
  padding: 7px 14px;
  border: 1px solid #c7d8ff;
  border-radius: var(--radius-pill);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    background var(--transition),
    border-color var(--transition),
    box-shadow var(--transition);
}

.report-chip:hover {
  background: #e3edff;
  border-color: var(--brand);
}

.report-chip:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.report-chip__icon {
  font-size: 0.95em;
  line-height: 1;
}

.report-chip__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 「见右侧面板 / 见下方报告面板」二选一：宽屏显示前者，窄屏显示后者（媒体查询切换） */
.report-chip__where--narrow {
  display: none;
}

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
  animation: chat-pulse 1.4s ease-in-out infinite;
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

/* ---------- 展开面板（JD / 粘贴 / 设置）通用 ---------- */
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

/* 模型设置面板：与「分析设置」同一栅格，但字段更多，整行铺满者占满宽度 */
.settings-panel__field--provider {
  flex: 0 0 160px;
  min-width: 160px;
}

.settings-panel__field--full {
  flex: 1 1 100%;
  min-width: 100%;
}

/* API Key 下方的隐私小字 */
.settings-panel__hint {
  font-size: 0.72rem;
  color: var(--text-muted);
}

/* 刷新模型列表行：按钮 + 状态文案同一行 */
.model-refresh {
  flex-direction: row;
  align-items: center;
  gap: var(--space-2);
}

.model-refresh__status {
  font-size: 0.78rem;
  color: var(--text-muted);
}

.model-refresh__status--ok {
  color: var(--brand);
}

.model-refresh__status--error {
  color: var(--danger);
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
  animation: chat-spin 0.7s linear infinite;
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

/* ---------- 动画 ---------- */
@keyframes chat-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes chat-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

@keyframes chat-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.8);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tool__spinner,
  .tool__step-spinner,
  .tool-btn__spinner {
    animation: none;
  }
  .typing span,
  .status-bar__dot,
  .to-bottom__dot {
    animation: none;
  }
}

/* ---------- 联网搜索结果（工具块内，默认折叠） ---------- */
.search {
  margin-top: 4px;
  padding-left: calc(1em + var(--space-2)); /* 与过程日志同缩进 */
}

.search__toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: var(--brand-active);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.search__toggle:hover {
  color: var(--brand);
}

.search__caret {
  font-size: 0.7rem;
  transition: transform var(--transition);
}

.search__caret.open {
  transform: rotate(90deg);
}

.search__list {
  list-style: none;
  margin: 6px 0 2px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.search__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.search__link {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--brand);
  word-break: break-word;
}

.search__link--plain {
  color: var(--text-secondary);
}

.search__snippet {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.55;
  color: var(--text-muted);
  /* 摘要最多 3 行 */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 侧栏：学习方案（主产出）+ 匹配度次级 ---------- */
.plan {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.plan__lead {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--text-secondary);
}

.plan__weeks {
  font-size: 1.05rem;
  font-weight: 800;
  color: var(--brand);
  margin-right: 4px;
}

.plan__role {
  color: var(--text-muted);
}

.plan__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan__week {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}

.plan__week-no {
  flex-shrink: 0;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--brand-active);
}

.plan__week-focus {
  min-width: 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}

.plan__more {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-muted);
}

/* 匹配度次级一行（有学习方案时） */
.report-panel__score-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border);
}

.report-panel__score-text {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-secondary);
}

/* 「下一步生成方案」提示（仅匹配分析阶段） */
.report-panel__next {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--brand-soft);
  color: var(--brand-active);
  font-size: 0.82rem;
  line-height: 1.55;
}

.report-panel__next strong {
  font-weight: 700;
}

/* ---------- 响应式 ---------- */
/* 窄屏（<960px）：两栏纵向堆叠——对话在上、报告面板在下且非 sticky。
   此时放开 .chat 的固定高度，让整页随内容自然滚动（左栏不再独立内滚），
   报告面板完整展开在对话下方，保证可用。 */
@media (max-width: 960px) {
  .chat {
    height: auto;
    min-height: 0;
  }

  .chat__main {
    flex-direction: column;
    /* 堆叠后不再需要内部高度约束，交还给整页滚动 */
    min-height: 0;
    gap: var(--space-5);
  }

  /* 左栏：放开内部滚动锁定，高度随内容（智能滚动逻辑仍在，
     但窄屏下滚动容器随页面滚动，贴底判断不受右栏影响）。 */
  .chat__left {
    min-height: 0;
  }

  .chat__scroll {
    /* 不再独占剩余高度；给一个舒适的最小高度，超出随页面滚动 */
    flex: 0 0 auto;
    min-height: 320px;
  }

  /* composer 改为静态流式排布（取消 sticky），使「对话 → composer → 报告面板」
     按自然顺序堆叠，整页一起滚动，避免 sticky composer 浮盖下方报告。 */
  .composer {
    position: static;
    /* 去掉为 sticky 准备的顶部渐隐背景，避免在流式排布下出现突兀渐变 */
    background: transparent;
  }

  /* 右栏：全宽、非 sticky、堆叠到对话下方 */
  .chat__right {
    flex: 0 0 auto;
    width: 100%;
  }

  /* 紧凑摘要面板：窄屏取消 sticky，随页面滚动堆叠在对话下方 */
  .report-panel {
    position: static;
  }

  /* chip 文案切换：隐藏「见右侧面板」，显示「见下方报告面板」 */
  .report-chip__where--wide {
    display: none;
  }

  .report-chip__where--narrow {
    display: inline;
  }
}

@media (max-width: 640px) {
  /* 注意：<960px 已切换为纵向堆叠（.chat 高度 auto、整页滚动），
     故此处不再重置 .chat 固定高度，避免与堆叠布局冲突。 */
  .composer__inner {
    padding: var(--space-3);
  }

  .bubble--user {
    max-width: 86%;
  }

  .bubble--assistant {
    max-width: 100%;
  }

  .entry__send {
    padding: 0 14px;
  }

  /* 小屏 composer 更紧凑，浮动按钮相应上移避免遮挡输入区 */
  .to-bottom {
    bottom: 130px;
  }
}
</style>
