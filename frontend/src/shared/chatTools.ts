// 对话工具名协议——前后端工具名的【单一来源】（修 M7：工具名漂移）。
// 后端实名见 backend/app/services/agent.py（web_search / analyze_match / generate_plan），
// 从未存在过 run_analysis 等旧别名，故无历史数据兼容负担。
// 任何按工具名分流的逻辑（图标、分析类判定、搜索结果挂载）都应引用此处常量，
// 禁止在组件里散落字符串字面量。

/** 联网搜索工具（会发 search_results 事件，挂载搜索关键词与结果列表）。 */
export const TOOL_WEB_SEARCH = 'web_search'
/** 第一步：简历×JD 匹配分析（会发 report 事件）。 */
export const TOOL_ANALYZE_MATCH = 'analyze_match'
/** 第二步：生成学习计划（同样会发 report 事件，报告含 roadmap）。 */
export const TOOL_GENERATE_PLAN = 'generate_plan'

/** 是否为「分析类」工具（两个会产出结构化报告 report 事件的工具）。 */
export function isAnalysisTool(name: string): boolean {
  return name === TOOL_ANALYZE_MATCH || name === TOOL_GENERATE_PLAN
}

/** 依据工具名给一个图标；联网搜索=放大镜，分析类=图表，默认扳手。 */
export function toolIcon(name: string): string {
  if (name === TOOL_WEB_SEARCH) return '🔍'
  if (isAnalysisTool(name)) return '📊'
  return '🛠'
}
