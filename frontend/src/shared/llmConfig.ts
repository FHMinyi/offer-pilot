// 前端自定义大语言模型（BYO LLM）全局配置：跨会话的全局偏好，用响应式单例 + localStorage 持久化。
// 持久化经 usePersistedRef（op.llm-config，JSON 编码，深度监听写回，try/catch 容错隐私模式）；
// 不写入 ChatPersistContext/会话 DB（避免 API Key 落库），故 types.ts 的 ChatPersistContext 与会话端点不改。

import type { LLMOverride } from '../types'
import { usePersistedRef } from './usePersistedRef'

const KEY = 'op.llm-config'

/** 六字段全空的默认配置（留空＝回退服务端 .env）。 */
function defaults(): LLMOverride {
  return { provider: '', base_url: '', api_key: '', model: '', model_resume: '', model_jd: '' }
}

/**
 * 全局响应式单例：模型配置（深度监听持久化，跨会话沿用）。
 * parse 钩子承载逐字段补默认：旧版本数据缺字段 / JSON 解析失败（抛错→hook 兜底），均用默认补全。
 */
export const llmConfig = usePersistedRef<LLMOverride>(KEY, defaults, {
  parse: (raw) => {
    const d = defaults()
    const o = JSON.parse(raw) as Partial<LLMOverride>
    return {
      provider: o.provider ?? d.provider,
      base_url: o.base_url ?? d.base_url,
      api_key: o.api_key ?? d.api_key,
      model: o.model ?? d.model,
      model_resume: o.model_resume ?? d.model_resume,
      model_jd: o.model_jd ?? d.model_jd,
    }
  },
  serialize: (v) => JSON.stringify(v),
  deep: true,
})

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
