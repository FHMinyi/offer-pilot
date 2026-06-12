<script setup lang="ts">
// BYO LLM 模型设置面板（自包含）：协议 / 接入点 Base URL / API Key / 三档模型
// + 「刷新模型列表」连通性测试。配置直接 v-model 绑全局响应式单例 llmConfig
// （localStorage 持久化由 llmConfig.ts 负责），不经 props 透传、不入会话记录。
//
// 开合经 open prop 由父级（ChatComposer 的「模型」按钮）控制，本组件实例常驻、
// 仅根节点 v-if——与拆分前「面板 v-if + 拉取状态 ref 留在视图」等价：
// modelList / 拉取状态在面板收起再展开（乃至 composer 折叠）间留存。
import { ref } from 'vue'
import { fetchLLMModels } from '../../api/client'
import { llmConfig } from '../../shared/llmConfig'

defineProps<{
  /** 面板是否展开：false 时不渲染 DOM（同拆分前 v-if 语义），组件实例不卸载 */
  open: boolean
}>()

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
</script>

<template>
  <!-- 模型设置（自定义大语言模型 BYO LLM）：按会话覆盖后端 .env，配置仅存本地浏览器 -->
  <div v-if="open" class="panel settings-panel settings-panel--model">
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

<style scoped>
/* 与 ChatComposer 的「分析设置」面板同一视觉语言。scoped 边界下父级样式
   命不中本组件内部元素，故 .panel / .settings-panel 基础规则在此持有本地副本
   （仅两处使用，不值得全局化；改动时与 ChatComposer 内同名规则保持一致）。 */
.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-muted);
  padding: var(--space-3);
}

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

/* 工具按钮（刷新模型列表）：与 composer 工具行同一 ghost 视觉 */
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

.tool-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
