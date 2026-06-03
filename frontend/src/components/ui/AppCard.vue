<script setup lang="ts">
// 通用卡片容器：白底、细边框、轻阴影、统一圆角与内边距。
// 可选标题 title；默认插槽放正文；具名插槽 actions 放右上角操作区。
withDefaults(
  defineProps<{
    /** 卡片标题，可选 */
    title?: string
    /** 标题下方的副标题/说明，可选 */
    subtitle?: string
    /** 是否去除内边距（用于自定义内部布局，如表格/图片铺满） */
    flush?: boolean
  }>(),
  {
    title: undefined,
    subtitle: undefined,
    flush: false,
  },
)
</script>

<template>
  <section class="card">
    <!-- 卡片头部：标题/副标题 + 操作插槽。仅在需要时渲染 -->
    <header v-if="title || subtitle || $slots.actions" class="card__head">
      <div class="card__heading">
        <h2 v-if="title" class="card__title">{{ title }}</h2>
        <p v-if="subtitle" class="card__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="card__actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="card__body" :class="{ 'card__body--flush': flush }">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}

.card__heading {
  min-width: 0;
}

.card__title {
  font-size: 1.05rem;
  font-weight: 650;
  color: var(--text);
}

.card__subtitle {
  margin-top: 2px;
  font-size: 0.875rem;
  color: var(--text-muted);
}

.card__actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.card__body {
  padding: var(--space-5);
}

.card__body--flush {
  padding: 0;
}
</style>
