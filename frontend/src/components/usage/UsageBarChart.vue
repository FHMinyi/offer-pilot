<script setup lang="ts">
// 手写 SVG 用量图表（无图表库，先例 ScoreRing.vue）。
//
// 两种指标：
//   tokens  —— 三色堆叠条形（hit=绿 / miss=橙 / output=主色）。
//              单序列：一张大堆叠图；多序列：small-multiples 每序列一张小图（窄屏换行）。
//   hitRate —— 单坐标系 0–100% 多折线（每序列一色 + 图例 + 80% 目标虚线）；
//              某桶 hit+miss==0 时断线并标灰点（不画 0%）。
//
// x 轴标签按 granularity 用外层 HTML 标签渲染（避免 SVG 文本被 viewBox 拉伸变形）。
// hover tooltip 显示该桶数值。空态画空网格 + 居中「暂无用量数据」。
import { computed, ref } from 'vue'
import type { UsageGranularity, UsageMetric, UsageSeries } from '../../types'

const props = withDefaults(
  defineProps<{
    /** 指标：tokens 堆叠条形 / hitRate 折线 */
    metric: UsageMetric
    /** 序列（group_by=none 时长度 1） */
    series: UsageSeries[]
    /** 全局共享桶轴（ISO 字符串），所有序列 buckets 与之逐桶对齐 */
    bucketStarts: string[]
    /** 时间粒度，决定 x 轴标签格式 */
    granularity: UsageGranularity
    /** 单图高度（像素），默认 220 */
    height?: number
    /** 折线模式各序列配色（不足时循环复用） */
    colors?: string[]
  }>(),
  {
    height: 220,
    colors: () => [
      'var(--brand)',
      '#0ea5e9',
      '#8b5cf6',
      '#ec4899',
      '#f59e0b',
      '#10b981',
      '#ef4444',
    ],
  },
)

// ---------- 通用几何 ----------
const VIEW_W = 600 // 内部 viewBox 宽（高随 height 走）
const PAD = { top: 16, right: 12, bottom: 8, left: 44 } // 留左轴刻度与上方空隙

// 是否有任意非零数据：决定空态。
const hasData = computed(() =>
  props.series.some((s) => s.buckets.some((b) => b.input_hit + b.input_miss + b.output > 0)),
)

const bucketCount = computed(() => props.bucketStarts.length)

// ---------- x 轴标签（外层 HTML） ----------
// day：本地「时」（如 14时）；week/month：M/D。每桶一格，疏密由 CSS 控制（过密时隔列显示）。
function fmtAxis(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  if (props.granularity === 'day') return `${d.getHours()}时`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

// hover tooltip 用完整本地时间。
function fmtFull(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  if (props.granularity === 'day') {
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`
  }
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const axisLabels = computed(() => props.bucketStarts.map(fmtAxis))
// 桶过多时隔列显示标签，避免拥挤（最多 ~12 个标签）。
const labelStep = computed(() => Math.max(1, Math.ceil(bucketCount.value / 12)))

// token 数 k 缩写。
function fmt(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  if (v < 1000) return String(v)
  const k = v / 1000
  return `${k >= 100 ? Math.round(k) : Number(k.toFixed(1))}k`
}

// ---------- hover 状态 ----------
// 当前悬停的 (序列下标, 桶下标)，null = 无。
const hover = ref<{ si: number; bi: number; x: number; y: number } | null>(null)
function onLeave(): void {
  hover.value = null
}

// ===================================================================
//  Token 堆叠条形
// ===================================================================
interface StackBar {
  x: number // 条左边界（viewBox 坐标）
  w: number // 条宽
  hitY: number
  hitH: number
  missY: number
  missH: number
  outY: number
  outH: number
  hit: number
  miss: number
  output: number
  total: number
}

// 给定一个序列 + 全局最大 total，算出每桶堆叠条的几何。
function stackBars(series: UsageSeries, maxTotal: number, h: number): StackBar[] {
  const plotW = VIEW_W - PAD.left - PAD.right
  const plotH = h - PAD.top - PAD.bottom
  const n = bucketCount.value
  if (n === 0 || maxTotal <= 0) return []
  const slot = plotW / n
  const barW = Math.max(2, slot * 0.62)
  const scale = plotH / maxTotal
  return series.buckets.slice(0, n).map((b, i) => {
    const x = PAD.left + slot * i + (slot - barW) / 2
    const hitH = b.input_hit * scale
    const missH = b.input_miss * scale
    const outH = b.output * scale
    // 从底部往上堆：output 在底、miss 中、hit 顶（顺序仅视觉，图例标注一致即可）
    const baseY = PAD.top + plotH
    const outY = baseY - outH
    const missY = outY - missH
    const hitY = missY - hitH
    return {
      x,
      w: barW,
      hitY,
      hitH,
      missY,
      missH,
      outY,
      outH,
      hit: b.input_hit,
      miss: b.input_miss,
      output: b.output,
      total: b.input_hit + b.input_miss + b.output,
    }
  })
}

// 全局最大 total（所有序列所有桶），让 small-multiples 共用同一纵向尺度，便于横向比较。
const maxTotal = computed(() => {
  let m = 0
  for (const s of props.series) {
    for (const b of s.buckets) m = Math.max(m, b.input_hit + b.input_miss + b.output)
  }
  return m
})

// 单序列时图更高、占满；多序列时每张小图矮一些（small-multiples）。
const isMulti = computed(() => props.series.length > 1)
const chartHeight = computed(() => (isMulti.value ? Math.round(props.height * 0.62) : props.height))
// 每序列一张图的几何（tokens 模式）；单序列也走这套，只是 series 长度 1。
// bars 按当前单图高度（chartHeight）计算，所有图共用 maxTotal 纵向尺度便于横向比较。
const tokenChartsSized = computed(() =>
  props.series.map((s, si) => ({
    si,
    label: s.label,
    provider: s.provider,
    bars: stackBars(s, maxTotal.value, chartHeight.value),
  })),
)

// ===================================================================
//  命中率折线
// ===================================================================
interface RatePoint {
  bi: number
  x: number
  y: number | null // null = 该桶 hit+miss==0（断线 + 灰点）
  rate: number | null
}

const rateLines = computed(() => {
  const h = props.height
  const plotW = VIEW_W - PAD.left - PAD.right
  const plotH = h - PAD.top - PAD.bottom
  const n = bucketCount.value
  const slot = n > 0 ? plotW / n : plotW
  // 点居中于每个桶槽。
  const xOf = (i: number): number => PAD.left + slot * i + slot / 2
  // y：0% 在底、100% 在顶。
  const yOf = (r: number): number => PAD.top + plotH * (1 - r / 100)
  return props.series.map((s, si) => {
    const points: RatePoint[] = s.buckets.slice(0, n).map((b, i) => {
      const denom = b.input_hit + b.input_miss
      if (denom <= 0) return { bi: i, x: xOf(i), y: null, rate: null }
      const rate = (b.input_hit / denom) * 100
      return { bi: i, x: xOf(i), y: yOf(rate), rate }
    })
    // 折线分段：跳过断点（y===null）把连续有值点连成多段 polyline。
    const segments: string[] = []
    let cur: string[] = []
    for (const p of points) {
      if (p.y === null) {
        if (cur.length > 1) segments.push(cur.join(' '))
        cur = []
      } else {
        cur.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      }
    }
    if (cur.length > 1) segments.push(cur.join(' '))
    return {
      si,
      label: s.label,
      provider: s.provider,
      color: props.colors[si % props.colors.length],
      points,
      segments,
    }
  })
})

// 80% 目标线 y 坐标。
const targetY = computed(() => {
  const plotH = props.height - PAD.top - PAD.bottom
  return PAD.top + plotH * (1 - 80 / 100)
})

// 命中率纵轴刻度（0/20/40/60/80/100）。
const rateTicks = computed(() => {
  const plotH = props.height - PAD.top - PAD.bottom
  return [0, 20, 40, 60, 80, 100].map((v) => ({
    v,
    y: PAD.top + plotH * (1 - v / 100),
  }))
})

// tokens 纵轴刻度（0 / 半 / 满），用 k 缩写。
const tokenTicks = computed(() => {
  const h = isMulti.value ? chartHeight.value : props.height
  const plotH = h - PAD.top - PAD.bottom
  const m = maxTotal.value
  if (m <= 0) return [] as { label: string; y: number }[]
  return [0, 0.5, 1].map((f) => ({
    label: fmt(Math.round(m * f)),
    y: PAD.top + plotH * (1 - f),
  }))
})

// ---------- hover 进出（token 条 / 折线点） ----------
function enterBar(si: number, bi: number, x: number, y: number): void {
  hover.value = { si, bi, x, y }
}

// hover 当前条/点的数值卡内容。
const hoverInfo = computed(() => {
  const hv = hover.value
  if (!hv) return null
  const s = props.series[hv.si]
  const b = s?.buckets[hv.bi]
  if (!b) return null
  const denom = b.input_hit + b.input_miss
  const rate = denom > 0 ? `${Math.round((b.input_hit / denom) * 100)}%` : '—'
  return {
    when: fmtFull(props.bucketStarts[hv.bi] ?? ''),
    label: s.label,
    hit: b.input_hit,
    miss: b.input_miss,
    output: b.output,
    total: b.input_hit + b.input_miss + b.output,
    rate,
    x: hv.x,
    y: hv.y,
  }
})
</script>

<template>
  <div class="chart" @mouseleave="onLeave">
    <!-- 图例 -->
    <div class="chart__legend">
      <template v-if="metric === 'tokens'">
        <span class="lg"><i class="lg__sw" :style="{ background: 'var(--tok-hit)' }" /> 命中</span>
        <span class="lg"><i class="lg__sw" :style="{ background: 'var(--tok-miss)' }" /> 未命中</span>
        <span class="lg"><i class="lg__sw" :style="{ background: 'var(--tok-output)' }" /> 输出</span>
      </template>
      <template v-else>
        <span v-for="ln in rateLines" :key="ln.si" class="lg">
          <i class="lg__sw" :style="{ background: ln.color }" />
          {{ ln.label }}
        </span>
        <span class="lg lg--target">
          <i class="lg__sw lg__sw--dash" /> 目标 80%
        </span>
      </template>
    </div>

    <!-- ============ 空态 ============ -->
    <div v-if="!hasData" class="chart__empty">
      <svg :viewBox="`0 0 ${VIEW_W} ${height}`" class="chart__svg" preserveAspectRatio="none">
        <line
          v-for="t in [0.25, 0.5, 0.75]"
          :key="t"
          :x1="PAD.left"
          :x2="VIEW_W - PAD.right"
          :y1="PAD.top + (height - PAD.top - PAD.bottom) * t"
          :y2="PAD.top + (height - PAD.top - PAD.bottom) * t"
          class="grid"
        />
      </svg>
      <span class="chart__empty-text">暂无用量数据</span>
    </div>

    <!-- ============ 命中率折线 ============ -->
    <div v-else-if="metric === 'hitRate'" class="chart__single">
      <svg :viewBox="`0 0 ${VIEW_W} ${height}`" class="chart__svg" preserveAspectRatio="none">
        <!-- 纵轴刻度网格 + 标注 -->
        <g v-for="t in rateTicks" :key="t.v">
          <line :x1="PAD.left" :x2="VIEW_W - PAD.right" :y1="t.y" :y2="t.y" class="grid" />
          <text :x="PAD.left - 6" :y="t.y + 3" class="axis-y">{{ t.v }}</text>
        </g>
        <!-- 80% 目标虚线 -->
        <line
          :x1="PAD.left"
          :x2="VIEW_W - PAD.right"
          :y1="targetY"
          :y2="targetY"
          class="target"
        />
        <!-- 每序列折线分段 -->
        <template v-for="ln in rateLines" :key="ln.si">
          <polyline
            v-for="(seg, segi) in ln.segments"
            :key="segi"
            :points="seg"
            fill="none"
            :stroke="ln.color"
            stroke-width="2"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
          <!-- 数据点：有值=彩点（可 hover）；断点=灰点 -->
          <template v-for="p in ln.points" :key="p.bi">
            <circle
              v-if="p.y !== null"
              :cx="p.x"
              :cy="p.y"
              r="3"
              :fill="ln.color"
              class="dot"
              @mouseenter="enterBar(ln.si, p.bi, p.x, p.y)"
            />
            <circle
              v-else
              :cx="p.x"
              :cy="PAD.top + (height - PAD.top - PAD.bottom)"
              r="2.4"
              class="dot dot--gap"
            />
          </template>
        </template>
      </svg>
      <!-- x 轴标签（HTML，避免 SVG 拉伸） -->
      <div class="chart__xaxis" :style="{ paddingLeft: `${(PAD.left / VIEW_W) * 100}%` }">
        <span
          v-for="(lb, i) in axisLabels"
          :key="i"
          class="xtick"
          :class="{ 'xtick--hidden': i % labelStep !== 0 }"
        >{{ lb }}</span>
      </div>
    </div>

    <!-- ============ Token 堆叠条形 ============ -->
    <div v-else class="chart__tokens" :class="{ 'chart__tokens--multi': isMulti }">
      <div
        v-for="c in tokenChartsSized"
        :key="c.si"
        class="tk"
      >
        <div v-if="isMulti" class="tk__title">
          {{ c.label }}<span v-if="c.provider" class="tk__provider">{{ c.provider }}</span>
        </div>
        <svg
          :viewBox="`0 0 ${VIEW_W} ${chartHeight}`"
          class="chart__svg"
          preserveAspectRatio="none"
        >
          <!-- 纵轴刻度 -->
          <g v-for="(t, ti) in tokenTicks" :key="ti">
            <line :x1="PAD.left" :x2="VIEW_W - PAD.right" :y1="t.y" :y2="t.y" class="grid" />
            <text :x="PAD.left - 6" :y="t.y + 3" class="axis-y">{{ t.label }}</text>
          </g>
          <!-- 堆叠条：output(底) / miss(中) / hit(顶) -->
          <g
            v-for="(bar, bi) in c.bars"
            :key="bi"
            @mouseenter="enterBar(c.si, bi, bar.x + bar.w / 2, bar.hitY)"
          >
            <rect
              v-if="bar.outH > 0"
              :x="bar.x"
              :y="bar.outY"
              :width="bar.w"
              :height="bar.outH"
              fill="var(--tok-output)"
            />
            <rect
              v-if="bar.missH > 0"
              :x="bar.x"
              :y="bar.missY"
              :width="bar.w"
              :height="bar.missH"
              fill="var(--tok-miss)"
            />
            <rect
              v-if="bar.hitH > 0"
              :x="bar.x"
              :y="bar.hitY"
              :width="bar.w"
              :height="bar.hitH"
              fill="var(--tok-hit)"
            />
            <!-- 透明命中区：保证零值桶也能 hover -->
            <rect
              :x="bar.x"
              :y="PAD.top"
              :width="bar.w"
              :height="chartHeight - PAD.top - PAD.bottom"
              fill="transparent"
            />
          </g>
        </svg>
        <div class="chart__xaxis" :style="{ paddingLeft: `${(PAD.left / VIEW_W) * 100}%` }">
          <span
            v-for="(lb, i) in axisLabels"
            :key="i"
            class="xtick"
            :class="{ 'xtick--hidden': i % labelStep !== 0 }"
          >{{ lb }}</span>
        </div>
      </div>
    </div>

    <!-- hover tooltip：跟随悬停条/点，显示该桶数值 -->
    <div
      v-if="hoverInfo"
      class="tip"
      :style="{ left: `${(hoverInfo.x / VIEW_W) * 100}%` }"
    >
      <div class="tip__when">{{ hoverInfo.when }}</div>
      <div v-if="isMulti || metric === 'hitRate'" class="tip__label">{{ hoverInfo.label }}</div>
      <div class="tip__row"><span class="tip__dot" style="background: var(--tok-hit)" />命中 {{ fmt(hoverInfo.hit) }}</div>
      <div class="tip__row"><span class="tip__dot" style="background: var(--tok-miss)" />未命中 {{ fmt(hoverInfo.miss) }}</div>
      <div class="tip__row"><span class="tip__dot" style="background: var(--tok-output)" />输出 {{ fmt(hoverInfo.output) }}</div>
      <div class="tip__total">总计 {{ fmt(hoverInfo.total) }} · 命中率 {{ hoverInfo.rate }}</div>
    </div>
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  width: 100%;
}

.chart__legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  font-size: 0.76rem;
  color: var(--text-secondary);
}

.lg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.lg__sw {
  width: 11px;
  height: 11px;
  border-radius: 3px;
  display: inline-block;
}

.lg__sw--dash {
  width: 16px;
  height: 0;
  border-top: 2px dashed var(--text-muted);
  border-radius: 0;
}

.lg--target {
  color: var(--text-muted);
}

.chart__svg {
  width: 100%;
  display: block;
  overflow: visible;
}

/* 网格 / 轴 */
.grid {
  stroke: var(--border);
  stroke-width: 1;
}

.axis-y {
  fill: var(--text-muted);
  font-size: 11px;
  text-anchor: end;
  font-variant-numeric: tabular-nums;
}

.target {
  stroke: var(--text-muted);
  stroke-width: 1.4;
  stroke-dasharray: 5 4;
  opacity: 0.7;
}

.dot {
  cursor: pointer;
}

.dot--gap {
  fill: var(--text-muted);
  opacity: 0.5;
}

/* x 轴标签（HTML 平铺，等分桶宽） */
.chart__xaxis {
  display: flex;
  margin-top: 4px;
}

.xtick {
  flex: 1;
  text-align: center;
  font-size: 0.68rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
}

.xtick--hidden {
  visibility: hidden;
}

/* small-multiples：多序列纵向排列，窄屏自动换行成网格 */
.chart__tokens--multi {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-4);
}

.tk__title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}

.tk__provider {
  margin-left: 6px;
  font-size: 0.68rem;
  font-weight: 400;
  color: var(--text-muted);
}

/* 空态 */
.chart__empty {
  position: relative;
}

.chart__empty-text {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  font-size: 0.86rem;
}

/* hover tooltip */
.tip {
  position: absolute;
  top: 24px;
  transform: translateX(-50%);
  pointer-events: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  padding: 8px 10px;
  font-size: 0.74rem;
  color: var(--text-secondary);
  white-space: nowrap;
  z-index: 5;
  font-variant-numeric: tabular-nums;
}

.tip__when {
  font-weight: 600;
  color: var(--text);
  margin-bottom: 3px;
}

.tip__label {
  color: var(--text-secondary);
  margin-bottom: 3px;
}

.tip__row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tip__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}

.tip__total {
  margin-top: 3px;
  padding-top: 3px;
  border-top: 1px solid var(--border);
  color: var(--text);
  font-weight: 600;
}
</style>
