<script setup lang="ts">
// 对话式主界面（路由 /）——OfferPilot 的产品新门面。
//
// 职责概览（拆分后本视图只保留「编排层」）：
//   · 以聊天形式承载「上传简历 / 添加 JD / 设定目标岗位与周数 → 发起分析」全流程。
//   · 用户气泡靠右、助手气泡靠左；助手回复以【有序 blocks】驱动渲染，
//     严格按事件到达顺序交错展示「对话 → 工具 → 对话 → 报告」
//     （气泡内部渲染在共享组件 AssistantBlocks，与回放页共用）。
//   · 布局为左右两栏：左栏=消息滚动区 + 底部「组合输入区」（ChatComposer 子组件：
//     附件 / 粘贴 / JD 库 / 分析与模型设置 / 思考强度 / 语气滑块 / 拖拽上传 / flash 提示）；
//     右栏=报告侧边面板（ReportSidePanel 子组件），sticky 展示【最新】一份匹配分析的
//     【紧凑摘要】（环形匹配度 + 目标岗位 + 简述 + 「查看完整报告」主按钮），
//     完整报告在 /result/:id 页（全展开）。面板可「隐藏」(reportPanelOpen=false)：
//     隐藏后右栏消失、聊天区占满宽度，经左侧边栏「报告 / 学习方案」入口重新展开；
//     新报告到达时自动展开（reportPanelOpen=true）。消息流里的 report block 不内联
//     整卡渲染，改为紧凑「引用 chip」，点击让报告面板滚到顶并短暂高亮（若面板被隐藏则
//     先展开）。窄屏（<960px）两栏纵向堆叠，报告面板移到对话下方且非 sticky。
//   · 智能滚动只作用于左栏消息容器（scrollRef），右栏不影响贴底判断。
//   · turns 的追加 / 截断 / 清空、与 SideNav 的信号协同（newChatSignal / reportNav /
//     openReportSignal）、路由 query.c 监听等编排职责留在本视图。
//
// 关键设计——助手消息的有序 blocks 模型：
//   原先把「文本」与「工具数组」分开存放，渲染时文字堆下面、工具堆上面，
//   无法还原真实发生顺序。现改为单一有序数组 blocks[]，每个事件「追加到末尾 /
//   更新末尾同类块」，从而严格保留交错顺序（见 useChatStream 内各 handler）。
//   发请求时仅把每条消息投影为纯文本（assistant 取其所有 text 块拼接），
//   工具 / 思考 / 报告不回传后端。
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ChatContext, ReasoningEffort, WeekItem } from '../types'
// 共享助手气泡渲染器：blocks / 错误条 / 无思考提示 / usage 小字 / 打字动效
// 全部由它渲染（与回放页 ConversationView 共用同一套）。
import AssistantBlocks from '../components/chat/AssistantBlocks.vue'
// 底部组合输入区（自包含子组件）：附件 / 粘贴 / JD 库 / 设置 / 工具行 / 拖拽 / flash
import ChatComposer from '../components/chat/ChatComposer.vue'
// 右栏报告紧凑摘要面板（纯展示子组件）：开合与信号协同仍由本视图编排
import ReportSidePanel from '../components/chat/ReportSidePanel.vue'
// 对话回合视图模型 + 纯函数（类型与序列化/投影/定位逻辑均移至 chatModel.ts）。
import {
  collapseAllReasoning,
  findLastReportBlock,
  localStamp,
  snapshotChatContext,
  toPayloadMessages,
} from '../shared/chatModel'
import type { AssistantTurn, ChatTurn } from '../shared/chatModel'
import { newChatSignal, reportNav, openReportSignal, isWide } from '../shared/appState'
// localStorage 持久化 ref 统一范式（读取容错 + watch 写回），见 usePersistedRef.ts
import { usePersistedRef } from '../shared/usePersistedRef'
// 智能滚动（贴底判定 / 回底 / 未读提示），只作用于左栏消息容器
import { useSmartScroll } from '../shared/useSmartScroll'
// 会话自动保存 / 续聊加载 / 新会话重置 + 本会话 token 用量累计（含保存竞态防护）
import { useConversationPersistence } from '../shared/useConversationPersistence'
// 一轮流式对话的 SSE 编排 + 停止（streaming / statusLine 单一来源）
import { useChatStream } from '../shared/useChatStream'

// ---------- 核心状态 ----------
// 对话消息列表（渲染源）。欢迎语为静态空状态，不入此列表，故不会回传后端。
const turns = reactive<ChatTurn[]>([])

// 对话上下文：随每条消息一并提交。weeks 默认 4。
// 以 reactive 直传 ChatComposer（项目现行风格）：素材增删由其直接写回。
const context = reactive<ChatContext>({
  resume_text: undefined,
  jd_texts: [],
  target_role: '',
  weeks: 4,
})

// 当前输入框文本（经 v-model 与 ChatComposer 同步；发送时由本视图读取并清空）。
const input = ref('')

// 思考强度：随 streamChat 以 reasoning_effort 提交，默认 'medium'（选项与文案在 ChatComposer）。
const reasoningEffort = ref<ReasoningEffort>('medium')

// E3 人设引擎（B5：单人设 + 语气滑块）：语气强度 0=最温柔…100=最严格，随对话以 context.tone 提交。
// 持久化 op.tone（数字字符串）：非数值/越界回退 50。滑块交互在 ChatComposer（v-model:tone）。
const tone = usePersistedRef<number>('op.tone', () => 50, {
  parse: (raw) => {
    const v = Number(raw)
    return Number.isFinite(v) && v >= 0 && v <= 100 ? v : undefined
  },
  serialize: String,
})

// 流式状态（streaming / statusLine）的单一来源在 useChatStream
// （见下方「发送与流式处理」段的接入；abortController 为其私有）。

// ---------- 会话自动保存 ----------
// conversationId / loadingConversation / sessionUsage 的单一来源在
// useConversationPersistence（见下方「会话自动保存」段的接入）。

// 最近一次匹配分析的 id（来自 report 事件）。随请求 context 回传，
// 供第二步 generate_plan 跨轮定位本次匹配分析。
const currentRunId = ref<number | null>(null)

// 路由：读取 query.c 以支持「历史续聊」（进入 /?c=<id> 加载该会话续聊）。
const route = useRoute()
const router = useRouter()

// ---------- DOM / 子组件引用 ----------
const scrollRef = ref<HTMLElement | null>(null) // 左栏消息滚动容器（智能滚动只作用于它）
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null) // 输入区（focusInput / flash）
const reportPanelRef = ref<InstanceType<typeof ReportSidePanel> | null>(null) // 报告面板（focusTop）

// ---------- 派生状态 ----------
// 是否已存在「可分析的素材」：有简历或至少一条 JD（发送守卫用；
// ChatComposer 内部另有同口径派生供发送按钮禁用态）。
const hasAttachments = computed(
  () =>
    Boolean(context.resume_text && context.resume_text.trim()) ||
    (context.jd_texts?.length ?? 0) > 0,
)

// 是否展示空状态欢迎语：尚无任何对话消息。
const showWelcome = computed(() => turns.length === 0)

// ---------- 报告侧边面板 ----------
// 最新报告：遍历所有 turns，取「最后一个」report block；无则 null。
// 右侧面板只展示这一份最新报告（历史报告在消息流里以紧凑引用 chip 呈现）。
const latestReport = computed(() => findLastReportBlock(turns))

// 报告侧栏开合：默认展开。隐藏后右栏消失、聊天区占满宽度，
// 经左侧边栏「报告 / 学习方案」入口重新展开。
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
// 面板内的预览列表 / 主按钮文案由 ReportSidePanel 自行派生，此处只为
// hasPlan（reportNav 同步 + 面板 props）保留计算。
const latestRoadmap = computed<WeekItem[]>(() => {
  const r = latestReport.value?.result.roadmap
  return Array.isArray(r) ? [...r].sort((a, b) => a.week - b.week) : []
})
// 是否已生成学习方案（有非空周计划）——决定侧栏以「学习方案」还是「匹配分析」为主角。
const hasPlan = computed(() => latestRoadmap.value.length > 0)

// ---------- 智能滚动 ----------
// 贴底判定 / 回底 / 未读提示由 useSmartScroll 承担（阈值默认 80px）。
// contentKey 追踪：消息条数、各助手消息的 blocks 数量、末块的文本长度 / 工具状态、
// 流式标记，以覆盖「新增气泡、增量文本、工具活动、报告到达」等所有会改变高度的情形。
const {
  atBottom,
  hasUnreadBelow,
  onScroll,
  scrollToBottom,
  jumpToBottom,
  resetToBottom,
} = useSmartScroll({
  scrollRef,
  contentKey: () =>
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
  isStreaming: () => streaming.value,
})

// ===================================================================
//  发送与流式处理
// ===================================================================

// 一轮 SSE 的编排（runChat）与停止由 useChatStream 承担；其契约：
// runChat 返回的 Promise resolve 即一轮完整收尾（含中止路径），收尾时经
// onTurnFinished 在此串接「折叠思考块 → 收尾贴底 → 自动保存」。
const { streaming, statusLine, runChat, stop } = useChatStream({
  effort: reasoningEffort,
  buildContext: () => snapshotChatContext(context, currentRunId.value, tone.value),
  onReportRunId: (id) => {
    // 记录最近一次匹配分析 id，供第二步 generate_plan 跨轮使用
    currentRunId.value = id
  },
  onUsage: (e) => addTurnUsage(e),
  onTurnFinished: (assistant) => {
    // 本轮结束：自动折叠所有思考块（用户仍可手动展开回看）
    collapseAllReasoning(assistant)
    // 收尾贴底：仅当用户仍在底部时跟随（上滑查看历史则不强拉回）
    void scrollToBottom()
    // 本轮结束后自动保存会话（不阻塞、失败仅告警）
    void persistConversation()
  },
})

// 点击发送（ChatComposer 的 send 事件，不带参）：组装用户消息与助手占位，发起流式对话。
async function send(): Promise<void> {
  if (streaming.value) return

  const raw = input.value.trim()
  // 文本为空但已有新素材：自动补一条引导文本（如「刚传完简历直接开始分析」）。
  if (!raw && !hasAttachments.value) return
  const userText = raw || '请基于我已提供的简历和 JD 开始分析。'

  // 1) 追加用户消息（输入清空后的高度复位由 ChatComposer 内 watch 自动完成）
  //    盖发送时刻（不可变，注入模型 + 气泡显示）
  turns.push({ role: 'user', text: userText, time: localStamp() })
  input.value = ''
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

// ===================================================================
//  会话自动保存
// ===================================================================

// 持久化 + 本会话 token 用量累计由 useConversationPersistence 承担
// （含「保存返回覆盖新对话 id」的 generation 竞态防护）；
// 滚动聚焦 / flash 提示 / 路由清理等视图职责经 onLoaded / onLoadError 留在本视图。
const {
  conversationId,
  loadingConversation,
  sessionUsage,
  hasSessionUsage,
  addTurnUsage,
  persist: persistConversation,
  load: loadConversation,
  reset: resetConversation,
} = useConversationPersistence({
  turns,
  context,
  tone,
  currentRunId,
  buildContext: () => snapshotChatContext(context, currentRunId.value, tone.value),
  onLoaded: () => {
    // 进入续聊：滚到底部，用户可直接继续对话
    resetToBottom()
    void scrollToBottom(true)
    // 续聊会话载入完成，聚焦输入框便于继续对话
    autoFocusInput()
  },
  onLoadError: (err) => {
    // 加载失败：提示（经 ChatComposer 的 flash 浮层）并回退为一段空白新对话
    // （去掉 query.c，避免反复重试）
    composerRef.value?.flash(
      err instanceof Error ? err.message : '加载历史会话失败，已切换为新对话',
      true,
    )
    if (route.query.c != null) void router.replace('/')
  },
})

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

// ---------- 新对话 ----------
// 清空当前对话并开始一段全新会话（conversationId 置空 → 下次保存即新建）。
// 同时去掉路由 query.c，避免续聊监听器把刚清空的会话重新加载回来。
function newConversation(): void {
  if (streaming.value) return
  turns.splice(0, turns.length)
  // 切换会话身份：conversationId 置空 + 累计清零 + 作废在途保存的 id 回填
  resetConversation()
  currentRunId.value = null
  statusLine.value = ''
  resetToBottom()
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
  // 回填后聚焦输入框（高度同步在 focusInput 内完成）
  composerRef.value?.focusInput()
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

// ---------- 输入框聚焦 ----------
// 让输入框获得焦点（聚焦同时会经 composer 的 focusin 展开输入区）。
// 仅宽屏自动聚焦：移动端自动聚焦会立刻弹出软键盘，打扰浏览，故跳过。
function autoFocusInput(): void {
  if (!isWide.value) return
  composerRef.value?.focusInput()
}

// 页面打开即聚焦输入框，用户可直接开始输入。
onMounted(autoFocusInput)

// ===================================================================
//  报告面板的视线引导与侧栏协同
// ===================================================================
// blocks 级渲染辅助已在 components/chat/AssistantBlocks.vue；
// 面板自身的滚顶 + 高亮在 ReportSidePanel.focusTop()。

// 点击消息流里的报告引用 chip：让右侧（或窄屏下方）报告面板滚到顶并短暂高亮，
// 帮助用户把视线引导到报告所在处。报告面板仅展示「最新」一份，故此处不按具体 block 定位。
// 若面板当前被隐藏，则先展开（reportPanelOpen=true）再滚动/高亮。
function focusReportPanel(): void {
  // 先确保面板可见（隐藏态下 <aside> 不渲染，需置位后等 DOM 更新才能拿到 ref）
  reportPanelOpen.value = true
  void nextTick(() => {
    reportPanelRef.value?.focusTop()
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
              <time v-if="turn.time" class="msg-time msg-time--user">{{ turn.time }}</time>
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

          <!-- 助手气泡（左）。显式判定 role 以便类型在该分支内收窄为助手消息。
               气泡内部（blocks / 错误条 / 无思考提示 / usage 小字 / 打字动效）由
               共享渲染器 AssistantBlocks 负责；报告块经 #report 插槽以紧凑
               引用 chip 呈现（chip 样式与点击定位逻辑留在本视图）。 -->
          <div v-else-if="turn.role === 'assistant'" class="msg msg--assistant">
            <div class="avatar avatar--assistant" aria-hidden="true">OP</div>
            <div class="msg__assistant-body">
              <AssistantBlocks
                :turn="turn"
                :live="turn.streaming === true"
                :readonly="false"
                :retry-disabled="streaming"
                @retry="retry(turn)"
              >
                <!-- 报告引用 chip：报告改在右侧面板展示，消息流里仅留紧凑引用。
                     点击让报告面板滚到顶并短暂高亮。窄屏文案改「见下方报告面板」。 -->
                <template #report>
                  <button
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
              </AssistantBlocks>
              <time v-if="turn.time" class="msg-time msg-time--assistant">{{ turn.time }}</time>
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

    <!-- ============ 底部组合输入区（ChatComposer 子组件） ============
         附件 chips / 粘贴 / JD 库 / 分析与模型设置 / 工具行 / 拖拽 / flash 整体内化；
         send 不带参（本视图自读 input 组装消息），stop 中止当前流式轮次。 -->
    <ChatComposer
      ref="composerRef"
      v-model="input"
      v-model:effort="reasoningEffort"
      v-model:tone="tone"
      :context="context"
      :streaming="streaming"
      :status-line="statusLine"
      :session-usage="sessionUsage"
      :has-session-usage="hasSessionUsage"
      @send="send"
      @stop="stop"
    />
      </div>
      <!-- /左栏 -->

      <!-- 右栏：报告【紧凑摘要】面板（ReportSidePanel 子组件）。
           仅当存在最新报告且面板未隐藏时渲染（v-if 开合留在本视图——面板随隐藏
           频繁卸载，reportNav / 信号协同放子组件会断 SideNav 重开链路）；
           宽屏 sticky，窄屏（媒体查询）回退为非 sticky 并堆叠到对话下方。 -->
      <aside v-if="latestReport && reportPanelOpen" class="chat__right">
        <ReportSidePanel
          ref="reportPanelRef"
          :report="latestReport"
          :has-plan="hasPlan"
          :current-run-id="currentRunId"
          @hide="hideReportPanel"
          @view-full="goToFullReport"
        />
      </aside>
    </div>
    <!-- /左右两栏外壳 -->

    <!-- 报告被隐藏时的重新展开入口已移到左侧边栏（SideNav 的「报告 / 学习方案」），
         统一视觉并避免原右下角悬浮角标与发送按钮重叠。 -->
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

/* 右栏：报告面板容器（面板卡片样式在 ReportSidePanel）。宽屏固定宽度。 */
.chat__right {
  flex: 0 0 380px;
  min-width: 0;
  /* 与左栏顶部对齐；高度由 sticky 面板自行约束 */
  align-self: stretch;
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
  animation: op-pulse 1.4s ease-in-out infinite;
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

/* 每条消息的时间戳小字（用户=发送时刻、助手=回复完成时刻） */
.msg-time {
  font-size: 0.72rem;
  color: var(--text-muted);
  opacity: 0.75;
  user-select: none;
}
.msg-time--assistant {
  display: block;
  margin-top: 4px;
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

/* ---------- 气泡 ----------
   .bubble / .bubble--user / .bubble--assistant 基础类已上移到
   styles/main.css 全局（欢迎语与 AssistantBlocks 多根组件共用）；
   此处只留本视图私有的欢迎语变体。 */

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

/* 思考过程 / 工具活动 / 打字指示 / 错误条等气泡内样式在 AssistantBlocks.vue；
   composer 全套样式在 ChatComposer.vue；报告面板卡片样式在 ReportSidePanel.vue。 */

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

/* ---------- 动画 ----------
   keyframes 已重命名 op-spin / op-bounce / op-pulse 并上移到 styles/main.css
   全局（scoped 会给动画名加 hash，跨组件按名引用会静默失效）。
   降级：用户偏好减少动效时，本视图残留的动效元素静止
   （气泡 / composer 内动效的降级在各子组件内自行处理）。 */
@media (prefers-reduced-motion: reduce) {
  .to-bottom__dot {
    animation: none;
  }
}

/* ---------- 响应式 ---------- */
/* 窄屏（<960px）：两栏纵向堆叠——对话在上、报告面板在下且非 sticky。
   此时放开 .chat 的固定高度，让整页随内容自然滚动（左栏不再独立内滚），
   报告面板完整展开在对话下方，保证可用。composer / 报告面板自身的窄屏
   降级（取消 sticky）在各自子组件的同断点媒体查询。 */
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

  /* 右栏：全宽、非 sticky、堆叠到对话下方 */
  .chat__right {
    flex: 0 0 auto;
    width: 100%;
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
     故此处不再重置 .chat 固定高度，避免与堆叠布局冲突。
     气泡放宽（.bubble--user / .bubble--assistant）已随全局气泡样式
     移入 styles/main.css 的同断点媒体查询。 */
  /* 小屏 composer 更紧凑（见 ChatComposer），浮动按钮相应上移避免遮挡输入区 */
  .to-bottom {
    bottom: 130px;
  }
}
</style>
