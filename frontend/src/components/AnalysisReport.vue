<script setup lang="ts">
// 可复用的「求职分析报告」组件。
// 同时供「结果页」(ResultView) 与「对话界面」渲染同一份 AnalysisResult：
//   A 顶部总览（匹配度 ScoreRing + 引擎/时间 + summary）
//   B 岗位画像 job_profile
//   C 技能缺口 skill_gap（必备缺口 / 加分缺口 / 已具备）
//   D 简历优化建议 resume_suggestions
//   E 学习路线 roadmap（按周时间线）
//   F 导出（复制 / 下载 Markdown）
//
// 数据来源约定：
//   - 报告主体只依赖 props.result。
//   - engine / targetRole / createdAt 为「展示用元信息」，可单独传入（如来自 AnalysisRun）；
//     未传时回退到 result 内同名字段，保证对话界面仅有 result 时也能正确展示。
//   - 传入 runId 时，额外提供一个跳转到完整报告页 /result/{runId} 的链接
//     （对话界面里报告卡通常需要「查看完整报告页」入口）。
import { computed, reactive, ref } from 'vue'
import type { AnalysisResult, GapItem, PerJob, PossessedItem } from '../types'
import AppCard from './ui/AppCard.vue'
import ScoreRing from './ui/ScoreRing.vue'
import SkillTag from './ui/SkillTag.vue'

const props = defineProps<{
  /** 完整分析结果（报告主体的唯一数据源） */
  result: AnalysisResult
  /** 分析引擎标识，如 'rule' | 'llm:openai'；缺省回退 result.engine */
  engine?: string
  /** 目标岗位；缺省回退 result.target_role */
  targetRole?: string
  /** 分析时间（ISO 字符串）；提供时展示「分析时间」 */
  createdAt?: string
  /** 对应分析记录 id；提供时展示「查看完整报告页」链接，跳转 /result/{runId} */
  runId?: number
  /**
   * 是否允许折叠（默认 true）。
   * - true（对话内）：默认折叠，显示概览 teaser + 展开/收起切换；有 runId 时显示「查看完整报告页」链接。
   * - false（完整报告页）：始终全展开，隐藏展开/收起切换，且不显示「查看完整报告页」链接（本身已在该页）。
   */
  collapsible?: boolean
  /** 所属会话 id；提供时「查看完整报告页」携带 ?from=<id>，使完整报告页左上角能返回该对话 */
  fromConversationId?: number
}>()

// 「查看完整报告页」目标：携带来源会话 id（若有），让完整报告页返回到对话而非新建。
const fullReportTo = computed(() => ({
  name: 'result' as const,
  params: { id: props.runId },
  ...(props.fromConversationId != null
    ? { query: { from: String(props.fromConversationId) } }
    : {}),
}))

// 默认可折叠；完整报告页传入 collapsible=false 时禁用折叠
const collapsible = computed(() => props.collapsible ?? true)

// ---------- 元信息（props 优先，回退到 result） ----------
const result = computed(() => props.result)
const engine = computed(() => props.engine ?? props.result.engine ?? '')
const targetRole = computed(
  () => props.targetRole ?? props.result.target_role ?? '',
)

// ---------- 展示辅助 ----------

/** 引擎友好展示：rule -> 规则模式；llm:openai -> LLM·openai */
function engineLabel(value: string): string {
  if (!value) return '未知引擎'
  if (value === 'rule') return '规则模式'
  if (value.startsWith('llm:')) {
    const vendor = value.slice('llm:'.length).trim()
    return vendor ? `LLM·${vendor}` : 'LLM'
  }
  return value
}

/** 优先级 -> SkillTag 配色变体（高/中/低 对应 high/mid/low） */
function priorityVariant(priority: GapItem['priority']): 'high' | 'mid' | 'low' {
  if (priority === '高') return 'high'
  if (priority === '中') return 'mid'
  return 'low'
}

/** 优先级排序权重：高 > 中 > 低 */
const PRIORITY_WEIGHT: Record<GapItem['priority'], number> = {
  高: 3,
  中: 2,
  低: 1,
}

/** 格式化日期时间为本地可读字符串；解析失败时原样返回 */
function formatDateTime(value: string): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  )
}

// 必备技能缺口：按优先级（高>中>低）再按 frequency 降序
const sortedMustHaveGaps = computed<GapItem[]>(() => {
  const list = result.value.skill_gap.must_have_gaps ?? []
  return [...list].sort((a, b) => {
    const byPriority = PRIORITY_WEIGHT[b.priority] - PRIORITY_WEIGHT[a.priority]
    if (byPriority !== 0) return byPriority
    return b.frequency - a.frequency
  })
})

const niceToHaveGaps = computed<GapItem[]>(
  () => result.value.skill_gap.nice_to_have_gaps ?? [],
)
const possessed = computed<PossessedItem[]>(
  () => result.value.skill_gap.possessed ?? [],
)

// 学习路线按 week 升序
const sortedRoadmap = computed(() => {
  const list = result.value.roadmap ?? []
  return [...list].sort((a, b) => a.week - b.week)
})

// ---------- 部分报告：空段落隐藏 ----------
// 「两步分析」中助手可能先发一份【部分报告】：roadmap=[]、resume_suggestions
// 可能为空，仅含匹配度 / 岗位画像 / 技能缺口。对这些空段落整段隐藏（不再展示
// “暂无…”占位文案），随后到达的完整报告再正常补齐这些段落。
const hasResumeSuggestions = computed(
  () => (result.value.resume_suggestions ?? []).length > 0,
)
const hasRoadmap = computed(() => sortedRoadmap.value.length > 0)

// ---------- 报告卡整体折叠 ----------
// 默认【折叠】：仅展示概览（匹配度 + summary + 元信息 + 一行 teaser）。
// 点击「展开详细信息」后才渲染岗位画像 / 技能缺口 / 简历优化建议 / 学习路线。
// 用组件内部 ref 控制，故每个报告卡（对话中可能多份）各自独立展开。
const userExpanded = ref(false)
// 实际是否展开：不可折叠时恒为 true；可折叠时取用户切换状态。
const expanded = computed(() => !collapsible.value || userExpanded.value)
function toggleExpanded(): void {
  userExpanded.value = !userExpanded.value
}

// ---------- 技能缺口：三段各自折叠 ----------
// 「必备 / 加分 / 已具备」改为上下三行的可折叠面板；默认仅展开「必备缺口」
// （最关键），其余收起以缩短篇幅，点头部切换。
const gapOpen = reactive({ must: true, nice: false, possessed: false })
function toggleGap(key: 'must' | 'nice' | 'possessed'): void {
  gapOpen[key] = !gapOpen[key]
}

// ---------- 概览 teaser：按数据有无拼接「必备缺口 N 项 / 已具备 M 项 / 路线 W 周」 ----------
// 学习路线周数：取最大 week（路线按周推进，最后一周即总周期）。
const roadmapWeeks = computed(() =>
  sortedRoadmap.value.length
    ? Math.max(...sortedRoadmap.value.map((wk) => wk.week))
    : 0,
)

interface TeaserStat {
  key: string
  label: string // 文案，如「必备缺口」
  value: number // 数值
  tone: 'danger' | 'success' | 'brand'
}

// 折叠态一行概览的统计项；roadmap 为空时不含「学习路线」项（兼容部分报告）。
const teaserStats = computed<TeaserStat[]>(() => {
  const stats: TeaserStat[] = [
    {
      key: 'must',
      label: '必备缺口',
      value: sortedMustHaveGaps.value.length,
      tone: 'danger',
    },
    {
      key: 'have',
      label: '已具备',
      value: possessed.value.length,
      tone: 'success',
    },
  ]
  if (hasRoadmap.value) {
    stats.push({
      key: 'weeks',
      label: '学习路线',
      value: roadmapWeeks.value,
      tone: 'brand',
    })
  }
  return stats
})

// 每条 JD 的折叠展开状态（默认收起）
const expandedJobs = ref<Record<number, boolean>>({})
function toggleJob(index: number): void {
  expandedJobs.value[index] = !expandedJobs.value[index]
}

// ---------- 导出：Markdown 生成 ----------

/**
 * 将整个 AnalysisResult 拼成结构化中文 Markdown。
 * 顺序：标题/概览 -> 岗位画像 -> 技能缺口 -> 简历优化建议 -> 学习路线。
 * 单独成函数，便于复制与下载复用。
 */
function buildMarkdown(): string {
  const r = result.value

  const lines: string[] = []
  const push = (s = '') => lines.push(s)
  // 列表项（带缩进层级）
  const li = (text: string, depth = 0) => push(`${'  '.repeat(depth)}- ${text}`)

  // ===== 概览 =====
  push(`# OfferPilot 求职分析报告`)
  push()
  push(`- 目标岗位：${targetRole.value || '未指定'}`)
  push(`- 匹配度：${r.match_score} / 100`)
  push(`- 分析引擎：${engineLabel(engine.value)}`)
  if (props.createdAt) {
    push(`- 分析时间：${formatDateTime(props.createdAt)}`)
  }
  push()
  if (r.summary) {
    push(`> ${r.summary}`)
    push()
  }

  // ===== 岗位画像 =====
  const jp = r.job_profile
  push(`## 一、岗位画像`)
  push()
  if (jp.titles.length) {
    push(`**目标岗位标题：** ${jp.titles.join('、')}`)
    push()
  }
  if (jp.responsibilities.length) {
    push(`### 核心职责`)
    jp.responsibilities.forEach((item) => li(item))
    push()
  }
  if (jp.requirements.length) {
    push(`### 任职要求`)
    jp.requirements.forEach((item) => li(item))
    push()
  }
  if (jp.tech_stack.length) {
    push(`### 技术栈`)
    push(jp.tech_stack.join('、'))
    push()
  }
  if (jp.jobs.length) {
    push(`### 各岗位明细`)
    push()
    jp.jobs.forEach((job: PerJob) => {
      const company = job.company ? `（${job.company}）` : ''
      push(`#### ${job.title}${company}`)
      if (job.must_have.length) {
        push(`- 必备技能：${job.must_have.map((s) => s.name).join('、')}`)
      }
      if (job.nice_to_have.length) {
        push(`- 加分技能：${job.nice_to_have.map((s) => s.name).join('、')}`)
      }
      push()
    })
  }

  // ===== 技能缺口 =====
  push(`## 二、技能缺口`)
  push()

  push(`### 必备技能缺口`)
  if (sortedMustHaveGaps.value.length) {
    sortedMustHaveGaps.value.forEach((gap) => {
      li(
        `**${gap.name}** ｜ 优先级：${gap.priority} ｜ 状态：${gap.gap_level} ｜ ${gap.frequency} 个岗位要求`,
      )
      if (gap.reason) li(`原因：${gap.reason}`, 1)
      if (gap.required_by.length) li(`要求来源：${gap.required_by.join('、')}`, 1)
    })
  } else {
    push(`无必备技能缺口，基础匹配良好。`)
  }
  push()

  push(`### 加分技能缺口`)
  if (niceToHaveGaps.value.length) {
    niceToHaveGaps.value.forEach((gap) => {
      li(`**${gap.name}** ｜ 优先级：${gap.priority} ｜ 状态：${gap.gap_level}`)
      if (gap.reason) li(`原因：${gap.reason}`, 1)
      if (gap.required_by.length) li(`要求来源：${gap.required_by.join('、')}`, 1)
    })
  } else {
    push(`暂无加分技能缺口。`)
  }
  push()

  push(`### 已具备技能`)
  if (possessed.value.length) {
    possessed.value.forEach((item) => {
      const evidence = item.evidence.length
        ? `（证据：${item.evidence.join('、')}）`
        : ''
      li(`**${item.name}**${evidence}`)
    })
  } else {
    push(`暂未识别到已具备技能。`)
  }
  push()

  // ===== 简历优化建议 =====
  push(`## 三、简历/项目优化建议`)
  push()
  if (r.resume_suggestions.length) {
    r.resume_suggestions.forEach((s, idx) => {
      push(`${idx + 1}. **${s.title}**`)
      if (s.detail) li(s.detail, 1)
      if (s.related_skills.length) {
        li(`相关技能：${s.related_skills.join('、')}`, 1)
      }
    })
  } else {
    push(`暂无优化建议。`)
  }
  push()

  // ===== 学习路线 =====
  push(`## 四、学习路线`)
  push()
  if (sortedRoadmap.value.length) {
    sortedRoadmap.value.forEach((wk) => {
      push(`### 第 ${wk.week} 周（预计 ${wk.estimated_hours} 小时）`)
      if (wk.focus_skills.length) {
        push(`- 聚焦技能：${wk.focus_skills.join('、')}`)
      }
      if (wk.tasks.length) {
        push(`- 学习任务：`)
        wk.tasks.forEach((t) => li(t, 1))
      }
      if (wk.deliverables.length) {
        push(`- 产出物：`)
        wk.deliverables.forEach((d) => li(d, 1))
      }
      if (wk.interview_focus.length) {
        push(`- 面试准备重点：`)
        wk.interview_focus.forEach((f) => li(f, 1))
      }
      push()
    })
  } else {
    push(`暂无学习路线。`)
  }

  push()
  push(`---`)
  push(`*本报告由 OfferPilot 生成。*`)

  return lines.join('\n')
}

// ---------- 导出动作 ----------
const copyHint = ref('') // 复制结果提示
let copyHintTimer: ReturnType<typeof setTimeout> | undefined

/** 短暂展示一条提示，自动消失 */
function flashHint(message: string): void {
  copyHint.value = message
  if (copyHintTimer) clearTimeout(copyHintTimer)
  copyHintTimer = setTimeout(() => {
    copyHint.value = ''
  }, 2400)
}

/** 复制 Markdown 到剪贴板 */
async function copyMarkdown(): Promise<void> {
  const md = buildMarkdown()
  if (!md) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(md)
      flashHint('已复制为 Markdown')
    } else {
      throw new Error('clipboard unavailable')
    }
  } catch {
    flashHint('复制失败，请手动选择文本')
  }
}

/** 下载 Markdown 为 .md 文件 */
function downloadMarkdown(): void {
  const md = buildMarkdown()
  if (!md) return
  const role = targetRole.value || '分析'
  // 文件名中去除可能影响下载的字符
  const safeRole = role.replace(/[\\/:*?"<>|\s]+/g, '_')
  const filename = `OfferPilot_${safeRole}_${props.runId ?? ''}.md`

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  flashHint('已开始下载 Markdown')
}
</script>

<template>
  <div class="report stack">
    <!-- A) 顶部总览 -->
    <AppCard>
      <div class="overview">
        <div class="overview__ring">
          <ScoreRing :score="result.match_score" :size="148" />
        </div>
        <div class="overview__main">
          <div class="overview__badges">
            <SkillTag :label="engineLabel(engine)" variant="must" />
            <span v-if="createdAt" class="overview__time">
              分析时间：{{ formatDateTime(createdAt) }}
            </span>
          </div>
          <h1 class="overview__role">
            {{ targetRole || '求职分析结果' }}
          </h1>
          <p v-if="result.summary" class="overview__summary">
            {{ result.summary }}
          </p>

          <!-- 一行概览 teaser：必备缺口 N 项 / 已具备 M 项 / 学习路线 W 周
               （路线为空时不含该项；折叠态下作为「先看要点」的速览）。
               不可折叠时（完整报告页）整份已展开，无需速览 → 隐藏。 -->
          <div v-if="collapsible" class="teaser">
            <span
              v-for="stat in teaserStats"
              :key="stat.key"
              class="teaser__item"
              :class="`teaser__item--${stat.tone}`"
            >
              <span class="teaser__label">{{ stat.label }}</span>
              <span class="teaser__value">{{ stat.value }}</span>
              <span class="teaser__unit">{{
                stat.key === 'weeks' ? '周' : '项'
              }}</span>
            </span>
          </div>

          <!-- 操作区：仅可折叠时显示「展开/收起」与「查看完整报告页」。
               不可折叠时整份恒展开，不渲染该区。 -->
          <div v-if="collapsible" class="overview__actions">
            <!-- 展开 / 收起整份报告详情；每个报告卡独立 -->
            <button
              type="button"
              class="btn toggle-btn"
              :aria-expanded="expanded"
              @click="toggleExpanded"
            >
              {{ expanded ? '收起' : '展开详细信息' }}
              <span class="toggle-btn__caret" :class="{ open: expanded }">
                ▾
              </span>
            </button>
            <!-- 提供 runId 时，给出跳转完整报告页的入口（对话界面报告卡使用） -->
            <RouterLink
              v-if="runId"
              class="overview__full-link"
              :to="fullReportTo"
            >
              查看完整报告页
              <span aria-hidden="true">→</span>
            </RouterLink>
          </div>
        </div>
      </div>
    </AppCard>

    <!-- B) 岗位画像（仅展开态渲染） -->
    <AppCard
      v-if="expanded"
      title="岗位画像"
      subtitle="综合所有目标 JD 提炼的岗位要求"
    >
      <div class="stack">
        <!-- 岗位标题 -->
        <div v-if="result.job_profile.titles.length" class="profile-block">
          <p class="section-title">目标岗位</p>
          <div class="tag-row">
            <SkillTag
              v-for="(t, i) in result.job_profile.titles"
              :key="`title-${i}`"
              :label="t"
            />
          </div>
        </div>

        <!-- 职责要点 -->
        <div
          v-if="result.job_profile.responsibilities.length"
          class="profile-block"
        >
          <p class="section-title">核心职责</p>
          <ul class="bullet-list">
            <li
              v-for="(item, i) in result.job_profile.responsibilities"
              :key="`resp-${i}`"
            >
              {{ item }}
            </li>
          </ul>
        </div>

        <!-- 任职要求（学历/年级/实习周期等） -->
        <div
          v-if="result.job_profile.requirements.length"
          class="profile-block"
        >
          <p class="section-title">任职要求</p>
          <ul class="bullet-list">
            <li
              v-for="(item, i) in result.job_profile.requirements"
              :key="`req-${i}`"
            >
              {{ item }}
            </li>
          </ul>
        </div>

        <!-- 技术栈（平铺标签） -->
        <div v-if="result.job_profile.tech_stack.length" class="profile-block">
          <p class="section-title">技术栈</p>
          <div class="tag-row">
            <SkillTag
              v-for="(t, i) in result.job_profile.tech_stack"
              :key="`tech-${i}`"
              :label="t"
              variant="nice"
            />
          </div>
        </div>

        <!-- 各 JD 明细（可折叠 must_have / nice_to_have） -->
        <div v-if="result.job_profile.jobs.length" class="profile-block">
          <p class="section-title">各岗位明细</p>
          <ul class="job-list">
            <li
              v-for="(job, i) in result.job_profile.jobs"
              :key="`job-${i}`"
              class="job-item"
            >
              <button
                type="button"
                class="job-item__head"
                :aria-expanded="!!expandedJobs[i]"
                @click="toggleJob(i)"
              >
                <span class="job-item__caret" :class="{ open: expandedJobs[i] }">
                  ▸
                </span>
                <span class="job-item__title">
                  {{ job.title }}
                  <span v-if="job.company" class="job-item__company">
                    · {{ job.company }}
                  </span>
                </span>
              </button>

              <div v-show="expandedJobs[i]" class="job-item__body">
                <div v-if="job.must_have.length" class="profile-block">
                  <p class="mini-title">必备技能</p>
                  <div class="tag-row">
                    <SkillTag
                      v-for="s in job.must_have"
                      :key="s.key"
                      :label="s.name"
                      variant="must"
                    />
                  </div>
                </div>
                <div v-if="job.nice_to_have.length" class="profile-block">
                  <p class="mini-title">加分技能</p>
                  <div class="tag-row">
                    <SkillTag
                      v-for="s in job.nice_to_have"
                      :key="s.key"
                      :label="s.name"
                      variant="nice"
                    />
                  </div>
                </div>
                <div
                  v-if="!job.must_have.length && !job.nice_to_have.length"
                  class="muted"
                >
                  该岗位未提取到结构化技能要求。
                </div>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </AppCard>

    <!-- C) 技能缺口（仅展开态渲染） -->
    <AppCard
      v-if="expanded"
      title="技能缺口"
      subtitle="对照目标岗位，标注需补齐与已具备的技能"
    >
      <!-- 上下三行可折叠面板：必备缺口 / 加分缺口 / 已具备 -->
      <div class="gap-stack">
        <!-- 必备技能缺口 -->
        <section class="gap-section gap-section--must">
          <button
            type="button"
            class="gap-section__head"
            :aria-expanded="gapOpen.must"
            @click="toggleGap('must')"
          >
            <span class="gap-section__title">
              必备技能缺口
              <span class="count-badge count-badge--danger">
                {{ sortedMustHaveGaps.length }}
              </span>
            </span>
            <span
              class="gap-section__chevron"
              :class="{ 'gap-section__chevron--open': gapOpen.must }"
              aria-hidden="true"
              >▾</span
            >
          </button>
          <div v-show="gapOpen.must" class="gap-section__body">
            <ul v-if="sortedMustHaveGaps.length" class="gap-items">
              <li
                v-for="gap in sortedMustHaveGaps"
                :key="gap.key"
                class="gap-card gap-card--must"
              >
                <div class="gap-card__top">
                  <span class="gap-card__name">{{ gap.name }}</span>
                  <SkillTag
                    :label="gap.priority"
                    :variant="priorityVariant(gap.priority)"
                  />
                  <SkillTag :label="gap.gap_level" variant="default" />
                </div>
                <p v-if="gap.reason" class="gap-card__reason">{{ gap.reason }}</p>
                <div class="gap-card__meta">
                  <span class="muted">{{ gap.frequency }} 个岗位要求</span>
                </div>
                <div v-if="gap.required_by.length" class="gap-card__sources">
                  <span class="gap-card__sources-label">要求来源：</span>
                  <SkillTag
                    v-for="(src, i) in gap.required_by"
                    :key="`mh-src-${gap.key}-${i}`"
                    :label="src"
                    variant="low"
                  />
                </div>
              </li>
            </ul>
            <p v-else class="muted gap-empty">无必备技能缺口，基础匹配良好。</p>
          </div>
        </section>

        <!-- 加分技能缺口 -->
        <section class="gap-section">
          <button
            type="button"
            class="gap-section__head"
            :aria-expanded="gapOpen.nice"
            @click="toggleGap('nice')"
          >
            <span class="gap-section__title">
              加分技能缺口
              <span class="count-badge count-badge--warning">
                {{ niceToHaveGaps.length }}
              </span>
            </span>
            <span
              class="gap-section__chevron"
              :class="{ 'gap-section__chevron--open': gapOpen.nice }"
              aria-hidden="true"
              >▾</span
            >
          </button>
          <div v-show="gapOpen.nice" class="gap-section__body">
            <ul v-if="niceToHaveGaps.length" class="gap-items">
              <li v-for="gap in niceToHaveGaps" :key="gap.key" class="gap-card">
                <div class="gap-card__top">
                  <span class="gap-card__name">{{ gap.name }}</span>
                  <SkillTag
                    :label="gap.priority"
                    :variant="priorityVariant(gap.priority)"
                  />
                  <SkillTag :label="gap.gap_level" variant="default" />
                </div>
                <p v-if="gap.reason" class="gap-card__reason">{{ gap.reason }}</p>
                <div v-if="gap.required_by.length" class="gap-card__sources">
                  <span class="gap-card__sources-label">要求来源：</span>
                  <SkillTag
                    v-for="(src, i) in gap.required_by"
                    :key="`nh-src-${gap.key}-${i}`"
                    :label="src"
                    variant="low"
                  />
                </div>
              </li>
            </ul>
            <p v-else class="muted gap-empty">暂无加分技能缺口。</p>
          </div>
        </section>

        <!-- 已具备技能 -->
        <section class="gap-section gap-section--have">
          <button
            type="button"
            class="gap-section__head"
            :aria-expanded="gapOpen.possessed"
            @click="toggleGap('possessed')"
          >
            <span class="gap-section__title">
              已具备技能
              <span class="count-badge count-badge--success">
                {{ possessed.length }}
              </span>
            </span>
            <span
              class="gap-section__chevron"
              :class="{ 'gap-section__chevron--open': gapOpen.possessed }"
              aria-hidden="true"
              >▾</span
            >
          </button>
          <div v-show="gapOpen.possessed" class="gap-section__body">
            <ul v-if="possessed.length" class="gap-items">
              <li
                v-for="item in possessed"
                :key="item.key"
                class="gap-card gap-card--have"
              >
                <div class="gap-card__top">
                  <span class="gap-card__name">{{ item.name }}</span>
                  <SkillTag label="已具备" variant="have" />
                </div>
                <div v-if="item.evidence.length" class="gap-card__sources">
                  <span class="gap-card__sources-label">简历证据：</span>
                  <SkillTag
                    v-for="(ev, i) in item.evidence"
                    :key="`ev-${item.key}-${i}`"
                    :label="ev"
                    variant="have"
                  />
                </div>
              </li>
            </ul>
            <p v-else class="muted gap-empty">暂未识别到已具备技能。</p>
          </div>
        </section>
      </div>
    </AppCard>

    <!-- D) 简历/项目优化建议（仅展开态；部分报告可能为空 → 整段隐藏） -->
    <AppCard
      v-if="expanded && hasResumeSuggestions"
      title="简历/项目优化建议"
      subtitle="针对当前简历可立即改进的方向"
    >
      <ul class="suggestion-list">
        <li
          v-for="(s, i) in result.resume_suggestions"
          :key="`sug-${i}`"
          class="suggestion"
        >
          <div class="suggestion__index">{{ i + 1 }}</div>
          <div class="suggestion__body">
            <h3 class="suggestion__title">{{ s.title }}</h3>
            <p v-if="s.detail" class="suggestion__detail">{{ s.detail }}</p>
            <div v-if="s.related_skills.length" class="tag-row">
              <SkillTag
                v-for="(sk, j) in s.related_skills"
                :key="`sug-${i}-sk-${j}`"
                :label="sk"
              />
            </div>
          </div>
        </li>
      </ul>
    </AppCard>

    <!-- E) 学习路线（仅展开态；部分报告可能为空 → 整段隐藏） -->
    <AppCard
      v-if="expanded && hasRoadmap"
      title="学习路线"
      subtitle="按周推进的补齐与面试准备计划"
    >
      <ol class="timeline">
        <li
          v-for="wk in sortedRoadmap"
          :key="`week-${wk.week}`"
          class="timeline__item"
        >
          <div class="timeline__marker">
            <span class="timeline__dot" aria-hidden="true" />
          </div>
          <div class="week-card">
            <header class="week-card__head">
              <h3 class="week-card__title">第 {{ wk.week }} 周</h3>
              <span class="week-card__hours">
                预计 {{ wk.estimated_hours }} 小时
              </span>
            </header>

            <div v-if="wk.focus_skills.length" class="week-card__section">
              <p class="mini-title">聚焦技能</p>
              <div class="tag-row">
                <SkillTag
                  v-for="(sk, i) in wk.focus_skills"
                  :key="`w${wk.week}-fs-${i}`"
                  :label="sk"
                  variant="must"
                />
              </div>
            </div>

            <div v-if="wk.tasks.length" class="week-card__section">
              <p class="mini-title">学习任务</p>
              <ul class="check-list">
                <li v-for="(t, i) in wk.tasks" :key="`w${wk.week}-task-${i}`">
                  {{ t }}
                </li>
              </ul>
            </div>

            <div v-if="wk.deliverables.length" class="week-card__section">
              <p class="mini-title">产出物</p>
              <ul class="check-list check-list--deliver">
                <li
                  v-for="(d, i) in wk.deliverables"
                  :key="`w${wk.week}-deliver-${i}`"
                >
                  {{ d }}
                </li>
              </ul>
            </div>

            <div v-if="wk.interview_focus.length" class="week-card__section">
              <p class="mini-title">面试准备重点</p>
              <ul class="check-list check-list--interview">
                <li
                  v-for="(f, i) in wk.interview_focus"
                  :key="`w${wk.week}-iv-${i}`"
                >
                  {{ f }}
                </li>
              </ul>
            </div>
          </div>
        </li>
      </ol>
    </AppCard>

    <!-- F) 导出 -->
    <AppCard
      title="导出报告"
      subtitle="将完整分析结果保存为 Markdown，便于归档或分享"
    >
      <div class="export">
        <div class="row wrap export__actions">
          <button class="btn btn-primary" type="button" @click="copyMarkdown">
            复制为 Markdown
          </button>
          <button class="btn" type="button" @click="downloadMarkdown">
            下载 Markdown
          </button>
        </div>
        <span
          v-if="copyHint"
          class="export__hint"
          role="status"
          aria-live="polite"
        >
          {{ copyHint }}
        </span>
      </div>
    </AppCard>
  </div>
</template>

<style scoped>
.report {
  gap: var(--space-5);
}

/* ---------- A 顶部总览 ---------- */
.overview {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.overview__ring {
  flex-shrink: 0;
}

.overview__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.overview__badges {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.overview__time {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.overview__role {
  font-size: 1.45rem;
}

.overview__summary {
  color: var(--text-secondary);
  line-height: 1.65;
}

.overview__full-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--brand);
}

.overview__full-link:hover {
  color: var(--brand-hover);
  gap: var(--space-2);
}

/* ---------- 概览 teaser（折叠态速览） ---------- */
.teaser {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.teaser__item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface-muted);
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.teaser__value {
  font-size: 1.02rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.teaser__unit {
  font-size: 0.78rem;
  color: var(--text-muted);
}

/* 语义配色：必备缺口=红 / 已具备=绿 / 学习路线=品牌蓝 */
.teaser__item--danger {
  background: var(--danger-soft);
  border-color: #f6c9c9;
  color: var(--danger);
}

.teaser__item--success {
  background: var(--success-soft);
  border-color: #bfe6cb;
  color: var(--success);
}

.teaser__item--brand {
  background: var(--brand-soft);
  border-color: #c7d8ff;
  color: var(--brand-active);
}

.teaser__item--danger .teaser__unit,
.teaser__item--success .teaser__unit,
.teaser__item--brand .teaser__unit {
  color: inherit;
  opacity: 0.85;
}

/* ---------- 概览操作区（展开/收起 + 完整报告链接） ---------- */
.overview__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.toggle-btn {
  padding: 7px 16px;
  font-size: 0.9rem;
}

.toggle-btn__caret {
  font-size: 0.85rem;
  line-height: 1;
  transition: transform var(--transition);
}

.toggle-btn__caret.open {
  transform: rotate(180deg);
}

/* ---------- 通用区块 ---------- */
.profile-block + .profile-block {
  margin-top: var(--space-1);
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.mini-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}

/* 项目符号列表 */
.bullet-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bullet-list li {
  position: relative;
  padding-left: var(--space-4);
  color: var(--text-secondary);
  line-height: 1.6;
}

.bullet-list li::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 0.65em;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand);
}

/* ---------- 各 JD 折叠 ---------- */
.job-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.job-item {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface);
}

.job-item__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  background: transparent;
  border: 0;
  text-align: left;
  font-weight: 550;
  color: var(--text);
}

.job-item__head:hover {
  background: var(--surface-muted);
}

.job-item__caret {
  display: inline-block;
  transition: transform var(--transition);
  color: var(--text-muted);
  font-size: 0.8rem;
}

.job-item__caret.open {
  transform: rotate(90deg);
}

.job-item__company {
  color: var(--text-muted);
  font-weight: 450;
}

.job-item__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4) var(--space-4);
  border-top: 1px solid var(--border);
}

/* ---------- C 技能缺口（上下三行可折叠面板） ---------- */
.gap-stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.gap-section {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
}

/* 折叠头：整行可点，左侧色条标识语义（必备=红 / 已具备=绿 / 加分=默认） */
.gap-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border: 0;
  border-left: 3px solid var(--border-strong);
  background: var(--surface-muted);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition);
}

.gap-section__head:hover {
  background: var(--brand-soft);
}

.gap-section--must .gap-section__head {
  background: var(--danger-soft);
  border-left-color: var(--danger);
}

.gap-section--have .gap-section__head {
  background: var(--success-soft);
  border-left-color: var(--success);
}

.gap-section__title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.95rem;
  font-weight: 650;
}

.gap-section__chevron {
  color: var(--text-muted);
  font-size: 0.9rem;
  transition: transform var(--transition);
}

.gap-section__chevron--open {
  transform: rotate(180deg);
}

.gap-section__body {
  padding: var(--space-4);
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  font-size: 0.78rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  background: var(--surface);
  color: var(--text-secondary);
}

.count-badge--danger {
  background: var(--danger);
  color: #fff;
}

.count-badge--warning {
  background: var(--warning);
  color: #fff;
}

.count-badge--success {
  background: var(--success);
  color: #fff;
}

.gap-items {
  /* 卡片在整行宽度内多列流式排布（窄屏自动回退单列），缩短整体高度 */
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr));
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.gap-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.gap-card__top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.gap-card__name {
  font-weight: 600;
  color: var(--text);
}

.gap-card__reason {
  font-size: 0.88rem;
  color: var(--text-secondary);
  line-height: 1.55;
}

.gap-card__meta {
  font-size: 0.82rem;
}

.gap-card__sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.gap-card__sources-label {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.gap-empty {
  padding: var(--space-3) 0;
}

/* ---------- D 简历优化建议 ---------- */
.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.suggestion {
  display: flex;
  gap: var(--space-3);
}

.suggestion__index {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-active);
  font-weight: 700;
  font-size: 0.85rem;
}

.suggestion__body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.suggestion__title {
  font-size: 1rem;
  color: var(--text);
}

.suggestion__detail {
  color: var(--text-secondary);
  line-height: 1.65;
}

/* ---------- E 学习路线（时间线） ---------- */
.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.timeline__item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: var(--space-3);
}

.timeline__marker {
  position: relative;
  display: flex;
  justify-content: center;
}

.timeline__dot {
  position: relative;
  z-index: 1;
  width: 12px;
  height: 12px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--brand);
  box-shadow: 0 0 0 4px var(--brand-soft);
}

/* 连接线：贯穿除最后一项外的标记列 */
.timeline__item:not(:last-child) .timeline__marker::before {
  content: '';
  position: absolute;
  top: 12px;
  bottom: calc(-1 * var(--space-4));
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  background: var(--border);
}

.week-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.week-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.week-card__title {
  font-size: 1.02rem;
}

.week-card__hours {
  font-size: 0.82rem;
  font-weight: 550;
  color: var(--brand-active);
  background: var(--brand-soft);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.check-list li {
  position: relative;
  padding-left: var(--space-5);
  color: var(--text-secondary);
  line-height: 1.55;
}

.check-list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  top: 0;
  color: var(--brand);
  font-weight: 700;
}

.check-list--deliver li::before {
  content: '◆';
  color: var(--warning);
  font-weight: 400;
  font-size: 0.85em;
  top: 0.1em;
}

.check-list--interview li::before {
  content: '★';
  color: var(--success);
  font-weight: 400;
}

/* ---------- F 导出 ---------- */
.export {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.export__hint {
  font-size: 0.88rem;
  font-weight: 550;
  color: var(--success);
}

/* ---------- 响应式 ---------- */
@media (max-width: 560px) {
  .overview {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-4);
  }
}
</style>
