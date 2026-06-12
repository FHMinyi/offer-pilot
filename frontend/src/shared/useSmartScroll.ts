// 消息滚动区的「智能贴底」逻辑（从 ChatView.vue 抽出，自包含）：
//   · atBottom：是否处于（或贴近）底部，由滚动事件实时维护；
//   · 内容增长（contentKey 变化）时仅在贴底状态下自动跟随到底；
//   · 用户上滑离开底部后不强拉回，流式中点亮「回到底部」按钮的未读提示点。
// 时机敏感：watch 保持默认 flush 'pre' + scrollToBottom 内部 nextTick 的组合
// 一字不动——连续 delta 帧下需「DOM 更新完再量高滚动」，改动任一侧都会错位。

import { nextTick, ref, watch, type Ref } from 'vue'

export interface SmartScrollOptions {
  /** 消息滚动容器（智能滚动只作用于它，其它区域不影响贴底判断）。 */
  scrollRef: Ref<HTMLElement | null>
  /**
   * 内容变化键：把所有会改变滚动高度的状态拼成字符串（消息条数、末块文本长度、
   * 工具状态等），其变化即触发一次「贴底跟随 / 未读提示」判定。
   */
  contentKey: () => string
  /** 是否流式进行中（决定用户离开底部时是否点亮未读提示点）。 */
  isStreaming: () => boolean
  /** 贴底判定阈值：滚动位置距底部 <= 此像素数视为「贴底」，默认 80。 */
  threshold?: number
}

export function useSmartScroll(opts: SmartScrollOptions) {
  const { scrollRef, contentKey, isStreaming, threshold = 80 } = opts

  // 是否处于（或贴近）底部。初始为真：空会话/首次进入应跟随最新内容。
  const atBottom = ref(true)
  // 流式中有新内容、但用户已上滑离开底部 → 用于「回到底部」按钮上的提示点。
  const hasUnreadBelow = ref(false)

  // 计算当前滚动容器是否贴底。
  function computeAtBottom(el: HTMLElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
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

  // 复位为「贴底 + 无未读」（新对话 / 续聊载入时使用；只改标记不滚 DOM，
  // 需要实际滚动时由调用方再调 scrollToBottom(true)）。
  function resetToBottom(): void {
    atBottom.value = true
    hasUnreadBelow.value = false
  }

  // 流式期间内容持续增长，监听内容变化键做「智能贴底」。
  // 行为：仅当 atBottom 为真时才自动贴底；用户上滑离开底部后不再强制拉回，
  // 此时若仍在流式中则点亮「回到底部」按钮的未读提示点。
  watch(contentKey, () => {
    if (atBottom.value) {
      void scrollToBottom()
    } else if (isStreaming()) {
      // 用户在上方查看历史，下方有新内容到达 → 提示有新内容
      hasUnreadBelow.value = true
    }
  })

  return { atBottom, hasUnreadBelow, onScroll, scrollToBottom, jumpToBottom, resetToBottom }
}
