// 前端自定义大语言模型（BYO LLM）全局配置：跨会话的全局偏好，用响应式单例 + localStorage 持久化。
// 仿 ChatView 里 tone 的 localStorage 范式（try/catch 容错隐私模式）；
// 不写入 ChatPersistContext/会话 DB（避免 API Key 落库），故 types.ts 的 ChatPersistContext 与会话端点不改。

import { ref, watch } from 'vue'
import type { LLMOverride } from '../types'

const KEY = 'op.llm-config'

/** 六字段全空的默认配置（留空＝回退服务端 .env）。 */
function defaults(): LLMOverride {
  return { provider: '', base_url: '', api_key: '', model: '', model_resume: '', model_jd: '' }
}

/**
 * 读取持久化配置（隐私模式下 localStorage 可能不可用 / 解析失败 / 缺字段，均用默认补全）。
 */
function read(): LLMOverride {
  const d = defaults()
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return d
    const o = JSON.parse(raw) as Partial<LLMOverride>
    return {
      provider: o.provider ?? d.provider,
      base_url: o.base_url ?? d.base_url,
      api_key: o.api_key ?? d.api_key,
      model: o.model ?? d.model,
      model_resume: o.model_resume ?? d.model_resume,
      model_jd: o.model_jd ?? d.model_jd,
    }
  } catch {
    return d
  }
}

/** 持久化当前配置（隐私模式：忽略写入失败）。 */
function persist(v: LLMOverride): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* 隐私模式：忽略持久化失败 */
  }
}

/** 全局响应式单例：模型配置（深度监听持久化，跨会话沿用）。 */
export const llmConfig = ref<LLMOverride>(read())
watch(llmConfig, persist, { deep: true })

/**
 * 生效覆盖：六字段经 trim 后全为空 → 返回 undefined（避免无谓透传），
 * 否则返回当前配置的浅拷贝随请求发给后端。
 */
export function effectiveOverride(): LLMOverride | undefined {
  const v = llmConfig.value
  const empty =
    !v.provider.trim() &&
    !v.base_url.trim() &&
    !v.api_key.trim() &&
    !v.model.trim() &&
    !v.model_resume.trim() &&
    !v.model_jd.trim()
  return empty ? undefined : { ...v }
}
