// 数字滚动到目标值的轻量缓动（E4 进度可视化润色）。
// 仅用 requestAnimationFrame，无第三方依赖；尊重 prefers-reduced-motion（直接落终值）。
// 用法：const display = useCountUp(() => props.progress.done_tasks)，模板里渲染 {{ display }}。

import { onUnmounted, ref, watch, type Ref } from 'vue'

/** 是否系统级「减少动态效果」——无障碍偏好，命中则不做滚动动画。 */
function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * 返回一个跟随 source 缓动的展示数字（整数）。
 * @param source 目标值取值函数（响应式来源，watch immediate 起算）
 * @param durationMs 缓动时长，默认 700ms；<=0 或减少动态效果时即时落值
 */
export function useCountUp(source: () => number, durationMs = 700): Ref<number> {
  const display = ref(0)
  const reduce = prefersReducedMotion()
  let raf = 0

  function animate(to: number): void {
    if (raf) cancelAnimationFrame(raf)
    if (reduce || durationMs <= 0) {
      display.value = to
      return
    }
    const from = display.value
    if (from === to) return
    const start = performance.now()
    const step = (now: number): void => {
      const t = Math.min(1, (now - start) / durationMs)
      const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic：收尾平缓
      display.value = Math.round(from + (to - from) * eased)
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  }

  watch(source, (v) => animate(Number.isFinite(v) ? v : 0), { immediate: true })
  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
  })

  return display
}
