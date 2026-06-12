<script setup lang="ts">
// token 用量汇总表（by_model / by_path 各渲染一次）。
// 列：名称 / 命中 / 未命中 / 输出 / 总计 / 命中率% / 调用次数。
// 命中率 = input_hit/(input_hit+input_miss)，分母 0 显示「—」（中性）；
// 红绿高亮：≥80% 绿 / 60–80% 橙 / <60% 红。默认按 input_miss 降序。数字 k 缩写。
import { computed } from 'vue'
import type { UsageGroupStat } from '../../types'

const props = defineProps<{
  /** 表标题（如「按模型」/「按功能」） */
  title: string
  /** 分组统计行 */
  rows: UsageGroupStat[]
}>()

// 命中率档位：none 分母为 0（显示「—」，中性）。
type HitLevel = 'none' | 'good' | 'mid' | 'bad'

interface Row {
  key: string
  label: string
  provider: string
  hit: number
  miss: number
  output: number
  total: number
  calls: number
  rate: number | null // null = 分母为 0
  level: HitLevel
}

// token 数 k 缩写：<1000 原样；≥1000 显示「x.xk」。
function fmt(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  if (v < 1000) return String(v)
  const k = v / 1000
  return `${k >= 100 ? Math.round(k) : Number(k.toFixed(1))}k`
}

function hitLevel(rate: number | null): HitLevel {
  if (rate === null) return 'none'
  if (rate >= 80) return 'good'
  if (rate >= 60) return 'mid'
  return 'bad'
}

// 按 input_miss 降序排好的行（最该优化的浮顶）+ 派生命中率/总计/档位。
const sorted = computed<Row[]>(() =>
  [...props.rows]
    .sort((a, b) => b.input_miss - a.input_miss)
    .map((r) => {
      const denom = r.input_hit + r.input_miss
      const rate = denom > 0 ? (r.input_hit / denom) * 100 : null
      return {
        key: r.key,
        label: r.label,
        provider: r.provider,
        hit: r.input_hit,
        miss: r.input_miss,
        output: r.output,
        total: r.input_hit + r.input_miss + r.output,
        calls: r.calls,
        rate,
        level: hitLevel(rate),
      }
    }),
)

// 命中率显示文本：null → 「—」；否则四舍五入到整数 + %。
function rateText(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate)}%`
}
</script>

<template>
  <div class="stat">
    <div class="stat__head">
      <h3 class="stat__title">{{ title }}</h3>
      <p class="stat__hint">命中率低 → 把固定指令前置，提升 prefix cache 命中</p>
    </div>

    <div v-if="sorted.length === 0" class="stat__empty">暂无数据</div>

    <div v-else class="stat__scroll">
      <table class="stat__table">
        <thead>
          <tr>
            <th class="col-name">名称</th>
            <th class="col-num">命中</th>
            <th class="col-num">未命中</th>
            <th class="col-num">输出</th>
            <th class="col-num">总计</th>
            <th class="col-num">命中率</th>
            <th class="col-num">调用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in sorted" :key="r.key">
            <td class="col-name">
              <span class="stat__name" :title="r.label">{{ r.label }}</span>
              <span v-if="r.provider" class="stat__provider">{{ r.provider }}</span>
            </td>
            <td class="col-num">{{ fmt(r.hit) }}</td>
            <td class="col-num">{{ fmt(r.miss) }}</td>
            <td class="col-num">{{ fmt(r.output) }}</td>
            <td class="col-num col-num--strong">{{ fmt(r.total) }}</td>
            <td class="col-num">
              <span class="rate" :class="`rate--${r.level}`">{{ rateText(r.rate) }}</span>
            </td>
            <td class="col-num">{{ r.calls }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.stat {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.stat__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.stat__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
  color: var(--text);
}

.stat__hint {
  margin: 0;
  font-size: 0.74rem;
  color: var(--text-muted);
}

.stat__empty {
  padding: var(--space-4);
  text-align: center;
  color: var(--text-muted);
  font-size: 0.86rem;
}

.stat__scroll {
  overflow-x: auto;
}

.stat__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
  font-variant-numeric: tabular-nums;
}

.stat__table th,
.stat__table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.stat__table th {
  text-align: right;
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.78rem;
}

.col-name {
  text-align: left !important;
}

.col-num {
  text-align: right;
  color: var(--text-secondary);
}

.col-num--strong {
  color: var(--text);
  font-weight: 600;
}

.stat__name {
  display: inline-block;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  color: var(--text);
}

.stat__provider {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: var(--radius-pill, 999px);
  background: var(--surface-muted);
  color: var(--text-muted);
  font-size: 0.68rem;
}

/* 命中率高亮：绿 / 橙 / 红 / 中性 */
.rate {
  display: inline-block;
  min-width: 40px;
  padding: 1px 7px;
  border-radius: var(--radius-pill, 999px);
  font-weight: 600;
}

.rate--good {
  color: var(--success);
  background: var(--success-soft);
}

.rate--mid {
  color: var(--warning);
  background: var(--warning-soft);
}

.rate--bad {
  color: var(--danger);
  background: var(--danger-soft);
}

.rate--none {
  color: var(--text-muted);
  background: var(--surface-muted);
}
</style>
