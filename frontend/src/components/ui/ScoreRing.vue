<script setup lang="ts">
import { computed } from 'vue'

// 环形匹配度进度：用 SVG 绘制圆环，中间显示数字与“匹配度”。
// 颜色随分段变化：<50 红 / 50-75 橙 / >=75 绿。
const props = withDefaults(
  defineProps<{
    /** 分数 0-100 */
    score: number
    /** 环直径（像素），默认 132 */
    size?: number
    /** 环描边粗细（像素），默认 12 */
    stroke?: number
  }>(),
  {
    size: 132,
    stroke: 12,
  },
)

// 将分数夹取到合法区间 0-100
const clamped = computed(() => {
  const n = Number.isFinite(props.score) ? props.score : 0
  return Math.max(0, Math.min(100, Math.round(n)))
})

// 几何参数
const radius = computed(() => (props.size - props.stroke) / 2)
const center = computed(() => props.size / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)

// 进度对应的 dash 偏移：值越大圆环填充越多
const dashOffset = computed(
  () => circumference.value * (1 - clamped.value / 100),
)

// 分段配色
const color = computed(() => {
  if (clamped.value < 50) return 'var(--danger)'
  if (clamped.value < 75) return 'var(--warning)'
  return 'var(--success)'
})

// 分段语义文案
const level = computed(() => {
  if (clamped.value < 50) return '匹配较低'
  if (clamped.value < 75) return '基本匹配'
  return '高度匹配'
})

// 中心文字随环径缩放：大环维持原观感（封顶 30.4px≈1.9rem / 12.5px≈0.78rem），
// 小环（如侧栏 44px 迷你环）按比例缩小，避免固定字号溢出圆环、压到相邻文案（错位）。
const valueFontPx = computed(() => Math.min(30.4, Math.round(props.size * 0.3)))
const captionFontPx = computed(() => Math.min(12.5, Math.round(props.size * 0.18)))
// 环太小放不下「匹配度」三字时直接隐藏，只保留中心数字（语义已由 aria-label/相邻文案承载）。
const showCaption = computed(() => props.size >= 72)
</script>

<template>
  <div
    class="ring"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="img"
    :aria-label="`匹配度 ${clamped} 分，${level}`"
  >
    <svg
      :width="size"
      :height="size"
      :viewBox="`0 0 ${size} ${size}`"
      class="ring__svg"
    >
      <!-- 背景轨道 -->
      <circle
        class="ring__track"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke-width="stroke"
      />
      <!-- 进度弧：从 12 点钟方向顺时针绘制 -->
      <circle
        class="ring__progress"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="color"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
        :transform="`rotate(-90 ${center} ${center})`"
      />
    </svg>

    <!-- 中心内容 -->
    <div class="ring__label">
      <span class="ring__value" :style="{ color, fontSize: `${valueFontPx}px` }">{{ clamped }}</span>
      <span v-if="showCaption" class="ring__caption" :style="{ fontSize: `${captionFontPx}px` }">匹配度</span>
    </div>
  </div>
</template>

<style scoped>
.ring {
  position: relative;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
}

.ring__svg {
  transform: rotate(0deg);
}

.ring__track {
  stroke: var(--surface-muted);
}

.ring__progress {
  /* 进度变化时平滑过渡 */
  transition:
    stroke-dashoffset 0.6s ease,
    stroke 0.3s ease;
}

.ring__label {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.ring__value {
  /* 字号由 :style 按 size 计算（见 valueFontPx），此处不再固定 */
  font-weight: 750;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.ring__caption {
  /* 字号由 :style 按 size 计算（见 captionFontPx） */
  margin-top: 4px;
  color: var(--text-muted);
}
</style>
