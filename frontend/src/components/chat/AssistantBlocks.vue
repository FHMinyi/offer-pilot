<script setup lang="ts">
// 共享的「助手气泡渲染器」——按有序 blocks 渲染一条助手回合的全部内容：
//   思考过程（可折叠）/ 普通文本（markdown）/ 工具活动（过程日志 + 搜索结果）
//   + 错误条（含重试）+ 无思考提示 + 本轮 token 用量小字 + 流式打字动效。
// 供 ChatView（流式）与 ConversationView（回放）共用同一套渲染，消灭两份
// 同名气泡渲染的双份维护（结构评审 H1/M1）。
//
// 共享视图模型约定（有意为之）：props.turn 是父视图传入的【共享 reactive 对象】，
// 本组件会直接 mutate 其折叠态字段（reasoningOpen / resultsOpen）——这是双方
// 约定的唯一写入面；「新思考块自动展开 / 收尾全折叠」等流式期写入仍由父侧
// 编排逻辑负责，组件只承担用户的手动切换。
//
// report 块不在此渲染：经作用域插槽 #report 交还父视图自行决定形态
// （ChatView 填紧凑引用 chip，ConversationView 填完整 <AnalysisReport>），
// 避免组件反向依赖父级报告面板逻辑。
//
// 样式切分约定：.bubble / .bubble--assistant 基础类与 op-* 动效 keyframes 在
// styles/main.css 全局（本组件为多根 fragment，父级 scoped 样式命不中根节点；
// scoped keyframes 会被加 hash 导致跨组件按名引用静默失效）。
import MarkdownText from '../MarkdownText.vue'
import type { AssistantBlock, AssistantTurn } from '../../shared/chatModel'
import { fmtTokens, hasBubble, isSafeUrl } from '../../shared/chatModel'
import { TOOL_WEB_SEARCH, toolIcon } from '../../shared/chatTools'

const props = defineProps<{
  /** 助手回合（共享 reactive 视图模型；本组件可直接改写其折叠态，见文件头约定） */
  turn: AssistantTurn
  /** 是否处于流式进行中（回放页恒为 false）：决定 spinner / 打字动效是否出现 */
  live: boolean
  /** 回放只读态：不渲染「重试」等会改写对话的交互按钮 */
  readonly: boolean
  /** 「重试」按钮是否禁用（如父视图正有别的轮次在流式中） */
  retryDisabled: boolean
}>()

const emit = defineEmits<{
  /** 点击错误条上的「重试」（父视图用本回合的历史快照重新发起） */
  (e: 'retry'): void
}>()

// ---------- 折叠态切换（直接写共享 reactive turn，见文件头约定） ----------
// 切换某个思考块的展开/收起。
function toggleReasoning(idx: number): void {
  props.turn.reasoningOpen[idx] = !props.turn.reasoningOpen[idx]
}

// 切换某个 web_search 工具块「搜索结果」的展开/收起（默认折叠）。
function toggleSearchResults(block: AssistantBlock): void {
  if (block.kind === 'tool') block.resultsOpen = !block.resultsOpen
}

// ---------- 渲染判定 ----------
// 工具块是否「正在运行」：仅流式中（live）且尚无结果（ok 未定）时成立。
// 非 live 下 ok===undefined（被「停止」中断的轮次）渲染中性「未完成」态：
// 灰点 + 原过程日志文案、无动画——修存量 bug「回放/续聊页中断轮次 spinner 永转」。
function toolRunning(block: Extract<AssistantBlock, { kind: 'tool' }>): boolean {
  return props.live && block.ok === undefined
}

// 末块是否为「正在运行的工具块」（它自身已有 spinner + 过程日志，无需再叠加打字动效）。
function lastBlockIsRunningTool(): boolean {
  const last = props.turn.blocks[props.turn.blocks.length - 1]
  return !!last && last.kind === 'tool' && toolRunning(last)
}

// 是否显示「工作中」打字动效：流式期间、且当前没有正在转的工具块时常驻，
// 覆盖「文字已出但仍在后台生成工具参数」等空窗期，避免看起来卡死。
function showWorking(): boolean {
  return props.live && !lastBlockIsRunningTool()
}
</script>

<template>
  <!-- 气泡：按 blocks 顺序交错渲染「思考 / 文本 / 工具」（渲染顺序即真实发生顺序）；
       报告块不入气泡，经下方 #report 插槽交还父视图 -->
  <div v-if="hasBubble(turn)" class="bubble bubble--assistant">
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
          @click="toggleReasoning(bi)"
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
           过程日志逐条累积；运行中（仅 live）末行带 spinner，完成后保留全部日志。 -->
      <div
        v-else-if="block.kind === 'tool'"
        class="tool"
        :class="{
          'tool--done': block.ok === true,
          'tool--fail': block.ok === false,
          'tool--running': toolRunning(block),
        }"
      >
        <div class="tool__head">
          <span class="tool__icon" aria-hidden="true">
            {{ toolIcon(block.name) }}
          </span>
          <span class="tool__label">{{ block.label }}</span>
          <span class="tool__state">
            <!-- 运行中且尚无过程日志：标题行兜底 spinner（有日志时 spinner 移至末行） -->
            <span
              v-if="toolRunning(block) && !(block.steps && block.steps.length)"
              class="tool__spinner"
              aria-hidden="true"
            />
            <span v-else-if="block.ok === true" class="tool__check">✓</span>
            <span v-else-if="block.ok === false" class="tool__cross">✕</span>
            <!-- 非 live 且 ok 未定（轮次被停止中断）：中性「未完成」灰点，无动画 -->
            <span
              v-else-if="block.ok === undefined && !live"
              class="tool__pending"
              title="本轮被中断，该工具未完成"
              aria-hidden="true"
            >·</span>
          </span>
        </div>
        <!-- 过程日志：每行小字、弱化，缩进于标题行之下；运行中（仅 live）末行带 spinner -->
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
                toolRunning(block) && si === (block.steps?.length ?? 0) - 1,
            }"
          >
            <span
              v-if="toolRunning(block) && si === (block.steps?.length ?? 0) - 1"
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
            block.name === TOOL_WEB_SEARCH &&
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
      v-if="showWorking()"
      class="typing"
      aria-label="处理中"
    >
      <span /><span /><span />
    </div>

    <!-- 错误条 + 重试（回放只读态不渲染重试按钮） -->
    <div v-if="turn.error" class="err" role="alert">
      <span class="err__text">{{ turn.error }}</span>
      <button
        v-if="!readonly"
        type="button"
        class="btn err__retry"
        :disabled="retryDisabled"
        @click="emit('retry')"
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

  <!-- 报告块：经作用域插槽交还父视图渲染（chip / 完整报告卡），与气泡互为兄弟节点 -->
  <template v-for="(block, bi) in turn.blocks" :key="`r-${bi}`">
    <slot v-if="block.kind === 'report'" name="report" :block="block" />
  </template>
</template>

<style scoped>
/* markdown 回复块：去掉 MarkdownText 自身的外边距塌陷影响，由父级 gap 控制间距 */
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

/* 运行中的最后一行：略微强调 */
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

/* 末行运行中的小 spinner（仅 live） */
.tool__step-spinner {
  flex-shrink: 0;
  align-self: center;
  width: 10px;
  height: 10px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: op-spin 0.7s linear infinite;
}

.tool__check {
  color: var(--success);
  font-weight: 700;
}

.tool__cross {
  color: var(--danger);
  font-weight: 700;
}

/* 中性「未完成」灰点：非 live 且 ok 未定（被停止中断的轮次），静态无动画 */
.tool__pending {
  color: var(--text-muted);
  font-weight: 700;
  line-height: 1;
  cursor: default;
}

.tool__spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: op-spin 0.7s linear infinite;
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
  animation: op-bounce 1.2s infinite ease-in-out;
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

/* 用户偏好减少动效：本组件内的 spinner / 打字三点全部静止 */
@media (prefers-reduced-motion: reduce) {
  .tool__spinner,
  .tool__step-spinner,
  .typing span {
    animation: none;
  }
}
</style>
