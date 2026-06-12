// localStorage 持久化 ref 的统一范式（L4）：读取 try/catch 容错 + watch 自动写回。
// 取代各处手写的「readXxx() + watch 写回」三件套；key 与存储编码由调用方钩子决定，
// 与既有线上数据一字不改（老用户本地数据零迁移）。
//
// 四个消费方与各自编码：
//   · ChatView tone（op.tone）：数字字符串，parse=Number + 0..100 范围校验，serialize=String；
//   · appState 侧栏折叠（op.sidebar.collapsed）：'1'/'0' 编码的布尔；
//   · MasteryDrawer 判定思考强度（op.mastery-effort）：裸枚举字符串，parse 做枚举校验；
//   · llmConfig BYO 模型配置（op.llm-config）：JSON，parse 逐字段补默认，deep 深度监听。
// 注意：device.ts 是「get-or-create」范式（读不到就生成并立即写入），不套此 hook。

import { ref, watch, type Ref } from 'vue'

export interface PersistedRefOptions<T> {
  /**
   * 自定义解码：raw 为 localStorage 中的原始字符串（key 不存在时不调用，直接用默认值）。
   * 返回 undefined 或抛错 → 回退默认值（容错脏数据/旧格式）。
   * 省略时把原始字符串按 T 直接返回（仅适用于 T 即 string 的场景）。
   */
  parse?: (raw: string) => T | undefined
  /** 自定义编码，默认 String(v)（仅适用于字符串/数字等可直接字符串化的 T）。 */
  serialize?: (v: T) => string
  /** 是否深度监听写回（对象型状态如 llmConfig 需要），默认 false。 */
  deep?: boolean
}

/**
 * 创建一个与 localStorage 同步的 ref：
 * - 初始化：读 key → parse 解码；key 缺失 / 解码失败（undefined 或抛错）/ localStorage
 *   不可用（隐私模式）均回退 defaultValue()。
 * - 变更：watch 写回 serialize(v)；写入失败静默吞（隐私模式不打扰用户）。
 */
export function usePersistedRef<T>(
  key: string,
  defaultValue: () => T,
  opts: PersistedRefOptions<T> = {},
): Ref<T> {
  const { parse, serialize = (v: T) => String(v), deep = false } = opts

  function read(): T {
    try {
      const raw = localStorage.getItem(key)
      if (raw === null) return defaultValue()
      if (!parse) return raw as unknown as T
      const parsed = parse(raw)
      return parsed === undefined ? defaultValue() : parsed
    } catch {
      return defaultValue()
    }
  }

  const state = ref(read()) as Ref<T>

  watch(
    state,
    (v) => {
      try {
        localStorage.setItem(key, serialize(v))
      } catch {
        /* 隐私模式：忽略持久化失败 */
      }
    },
    { deep },
  )

  return state
}
