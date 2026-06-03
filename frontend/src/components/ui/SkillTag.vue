<script setup lang="ts">
// 小圆角技能标签。通过 variant 区分语义配色：
//   default 中性
//   must    必备技能（强调）
//   nice    加分技能
//   have    已具备（成功色）
//   high/mid/low 优先级三档（红/橙/灰）
withDefaults(
  defineProps<{
    /** 标签文案 */
    label: string
    /** 配色变体 */
    variant?: 'default' | 'must' | 'nice' | 'have' | 'high' | 'mid' | 'low'
  }>(),
  {
    variant: 'default',
  },
)
</script>

<template>
  <span class="tag" :class="`tag--${variant}`">{{ label }}</span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  font-size: 0.8rem;
  font-weight: 550;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 中性默认 */
.tag--default {
  background: var(--surface-muted);
  border-color: var(--border);
  color: var(--text-secondary);
}

/* 必备技能：品牌主色强调 */
.tag--must {
  background: var(--brand-soft);
  border-color: #c7d8ff;
  color: var(--brand-active);
}

/* 加分技能：中性偏柔，弱于必备 */
.tag--nice {
  background: var(--surface-muted);
  border-color: var(--border-strong);
  color: var(--text-secondary);
}

/* 已具备：成功色 */
.tag--have {
  background: var(--success-soft);
  border-color: #bfe6cb;
  color: var(--success);
}

/* 优先级：高 = 红 */
.tag--high {
  background: var(--danger-soft);
  border-color: #f6c9c9;
  color: var(--danger);
}

/* 优先级：中 = 橙 */
.tag--mid {
  background: var(--warning-soft);
  border-color: #f4d6ad;
  color: var(--warning);
}

/* 优先级：低 = 灰 */
.tag--low {
  background: var(--surface-muted);
  border-color: var(--border);
  color: var(--text-muted);
}
</style>
