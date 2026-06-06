"""流式对话 Agent（PRD 第二阶段：引入可控的 Agent 编排）。

一轮对话内：助手可以先用自然语言说话、按需调用工具（联网搜索 / 运行结构化分析），
再结合结果继续解释、追问。全程以 SSE 事件流式产出，让用户实时看到 AI 在做什么。

工具：
- web_search：联网了解某岗位方向当前常见技能/框架（弥补 JD 未写明的“行业默认”）。
- run_analysis：基于简历 + JD 运行既有 pipeline，产出结构化报告并持久化。

未启用 LLM（或非 openai 协议）时，降级为脚本化流程：收集简历/JD → 跑规则分析 → 出报告，
保证离线也能用。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from ..models import AnalysisRun, JobPosting, Resume
from . import llm, pipeline, search
from .journey import ensure_journey
from .materialize import materialize_tasks

# 工具调用循环上限，防止无限调用
_MAX_STEPS = 5

Event = tuple[str, dict]  # (事件类型, data)


def _materialize_safe(db: Session, run: AnalysisRun, user_id: str) -> None:
    """物化有状态闭环（ensure_journey + materialize_tasks）旁路调用。

    失败降级「有报告无 Task」，绝不中断 SSE 流（generate_plan 在生成器内 commit）。
    """
    try:
        journey = ensure_journey(db, run, user_id)
        materialize_tasks(db, run, user_id, journey)
    except Exception:  # noqa: BLE001
        db.rollback()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索，用于了解某个岗位方向【当前】常见的技能、框架与要求，或核实较新的信息。"
                "当目标岗位较新或较细分（如 AI Agent 开发、大模型应用），JD 可能未写全行业默认技能时，"
                "应先用它检索。返回若干网页摘要。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，可中文或英文"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_match",
            "description": (
                "【第一步】基于简历与目标 JD 运行匹配分析，产出匹配度、岗位画像、技能缺口与简历优化建议"
                "（此步【不】生成学习路线）。当已掌握简历且至少有一份 JD（或你已通过搜索整理出常见要求）时调用。"
                "若简历/JD 是用户在对话中直接粘贴的（而非附件），必须原样填入 resume_text / jd_texts。"
                "调用后你会拿到 analysis_run_id，请据此先向用户反问关键信息，再用 generate_plan 生成学习路线。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_role": {"type": "string", "description": "目标岗位方向，如 前端实习、AI Agent 开发"},
                    "resume_text": {
                        "type": "string",
                        "description": "可选。当简历是用户在对话里直接给出、而非附件时，把简历全文原样填入。",
                    },
                    "jd_texts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。当 JD 是用户在对话里直接给出、而非附件时，把每条 JD 原文填入。",
                    },
                    "extra_jd": {
                        "type": "string",
                        "description": (
                            "可选。把你通过搜索/知识整理出的该岗位【常见要求】写成一段要求文本，"
                            "将作为附加 JD 并入分析，让结果包含 JD 未明说但行业默认的技能。"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_plan",
            "description": (
                "【第二步】生成个性化的分周学习/面试路线并补全报告。"
                "【仅在用户已经回答了你的关键问题之后调用】；【不要】在 analyze_match 的同一轮内调用本工具。"
                "analysis_run_id 可省略（系统会自动使用最近一次匹配分析）；不要为生成计划而重复调用 analyze_match。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "analysis_run_id": {"type": "integer", "description": "可选。analyze_match 返回的分析 id；省略则用最近一次匹配分析"},
                    "weeks": {"type": "integer", "description": "学习路线周数，1-12"},
                    "weekly_hours": {"type": "integer", "description": "用户每周可投入的学习小时数"},
                    "timeline_weeks": {"type": "integer", "description": "距离目标到岗/截止还有几周（会覆盖 weeks）"},
                    "focus_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用户最想优先补强/深入的技能名列表",
                    },
                    "learning_style": {"type": "string", "description": "用户偏好的学习方式（如 项目驱动/看视频/刷题）"},
                },
                "required": [],
            },
        },
    },
]


# 人设注册表（B5：单人设 + 语气滑块，预留三人设结构）。
# E3 仅启用 default；coach/senior/butler 作为预留键，后续接入命名人格时再填措辞。
PERSONAS: dict[str, str] = {
    "default": "OfferPilot 的 AI 求职规划助手",
    # 预留（B5/里程碑二后续）：
    # "coach": "用户的私人求职教练",
    # "senior": "带用户的学长 / 学姐",
    # "butler": "用户的求职管家",
}


def _tone_directive(tone: int) -> str:
    """把语气强度 0..100 映射为系统提示里的「语气」指令（E3：理智脑不变、情感脑可调）。

    无论松紧都守住底线：基于事实、不编造、不报具体 Offer 概率（B7）。
    """
    t = max(0, min(100, int(tone)))
    if t <= 20:
        style = "语气非常温柔、充满鼓励与共情：先共情再建议，多肯定进步、淡化措辞尖锐感，像贴心的伙伴陪着用户。"
    elif t <= 40:
        style = "语气偏鼓励、温和：以正向激励为主，指出不足时也尽量委婉。"
    elif t <= 60:
        style = "语气平衡：既肯定做得好的，也直言关键差距，给中肯、可执行的建议。"
    elif t <= 80:
        style = "语气偏严格、直接：坦诚指出差距与风险，标准更高，少铺垫多干货，像认真的教练。"
    else:
        style = "语气严格、不留情面：直接点破短板与风险、明确说出可能投不上的代价，高标准督促，像严厉的教练鞭策用户。"
    return (
        f"【语气强度 {t}/100】{style} "
        "无论语气松紧，都必须基于事实、不编造、不夸大；可给趋势与相对进展，但不报具体的「Offer 概率」数字。"
    )


def _now_str(client_time: str) -> str:
    """优先用前端传入的本地时间，否则回退服务器时间。"""
    if client_time and client_time.strip():
        return client_time.strip()
    from datetime import datetime

    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _system_prompt(context: dict, client_time: str = "") -> str:
    resume_text = (context.get("resume_text") or "").strip()
    jd_texts = [t for t in (context.get("jd_texts") or []) if t and t.strip()]
    role = context.get("target_role") or "（未指定，可询问用户）"
    weeks = context.get("weeks") or 4
    now = _now_str(client_time)
    # E3 人设引擎：单人设 + 语气滑块（理智脑/流程不变，仅调情感脑措辞）
    persona = context.get("persona") or "default"
    persona_desc = PERSONAS.get(persona, PERSONAS["default"])
    tone_directive = _tone_directive(context.get("tone", 50))

    # 把已附材料的实际内容给模型，避免它以为“看不到内容”而反复索取（截断防止过长）
    material: list[str] = []
    if resume_text:
        material.append(
            "【已附简历】run_analysis 会自动使用其全文，无需让用户重复粘贴：\n" + resume_text[:4000]
        )
    else:
        material.append("【简历】用户尚未提供，请简洁地向其索取（可上传 PDF 或粘贴文本）。")
    if jd_texts:
        joined = "\n---\n".join(t[:2000] for t in jd_texts)
        material.append(f"【已附 {len(jd_texts)} 条 JD】run_analysis 会自动使用其全文：\n" + joined)
    else:
        material.append("【JD】用户尚未提供，请向其索取至少一条目标岗位 JD。")

    return (
        f"你是 {persona_desc}，面向应届生和实习求职者。"
        "你的目标是围绕目标岗位，把简历、JD 与学习/面试准备串成可执行闭环。\n\n"
        "工作方式（务必按此两步走）：\n"
        "1. 缺简历或 JD 时简洁索取；用户在对话里直接粘贴的简历/JD（而非附件），调用工具时原样填入 resume_text / jd_texts。\n"
        "2. 对较新或细分的岗位方向（如 AI Agent 开发、大模型应用），JD 常没写全行业默认技能——"
        "先用 web_search 检索该方向当前常见技能与框架，然后【务必】把检索到的【具体技术栈名称】"
        "（例如 LangChain、LangGraph、RAG、向量数据库 Qdrant/Milvus、MCP、Prompt 工程、模型微调 等，"
        "而不是只写笼统的“熟悉相关框架”）整理成一段要求文本，通过 analyze_match 的 extra_jd 参数并入分析；"
        "否则分析会漏掉这些新兴技能。常规岗位可直接分析。\n"
        "3. 【第一步】调用 analyze_match 得到匹配度、岗位画像、技能缺口与简历优化建议（报告卡会自动渲染），"
        "用中文简要点出最该优先补强的 1-3 项及原因。此步【不要】生成学习路线。\n"
        "4. 然后【主动反问用户 2-4 个生成学习路线必需的关键信息】：每周可投入多少小时？距离目标到岗/截止还有几周？"
        "偏好的学习方式（项目驱动 / 看视频 / 刷题等）？最想优先补强或深入哪些方向？是否有可改造的现成项目？"
        "一次把问题问清后【就停下——本轮到此结束，等待用户在新消息中回答】。"
        "【绝对不要】在问问题的同一轮里调用 generate_plan，也不要替用户臆测答案。\n"
        "5. 【第二步，下一轮】只有当用户在【新的一条消息】里回答之后，才调用 generate_plan"
        "（analysis_run_id 可省略，系统会用最近一次匹配分析；并传 weekly_hours / timeline_weeks / focus_skills / "
        "learning_style / weeks 等用户已给的偏好）生成个性化学习路线，随后简要说明计划思路与本周重点。"
        "不要为生成计划而重复调用 analyze_match。\n\n"
        "风格：中文、简洁、具体、不说空话。\n"
        f"{tone_directive}\n\n"
        f"当前时间：{now}。涉及“当前/最新/今年”等信息时以此为准；"
        "联网检索时请使用与该时间匹配的时间范围（如当前年份），不要默认使用过时的年份。\n\n"
        f"目标岗位：{role}；学习路线周数：{weeks}。\n\n" + "\n\n".join(material)
    )


def run_turn(
    messages: list[dict],
    context: dict,
    db: Session,
    reasoning_effort: str = "medium",
    client_time: str = "",
    user_id: str = "local",
) -> Iterator[Event]:
    """运行一轮对话，产出 SSE 事件流。

    user_id：归属标签，由路由层 Depends(get_current_user) 解出后显式穿透到物化（§5.3）。
    """
    if not llm.streaming_supported():
        yield from _scripted_turn(context, db, user_id)
        return

    llm_messages: list[dict] = [{"role": "system", "content": _system_prompt(context, client_time)}]
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            llm_messages.append({"role": role, "content": content})

    # 本轮状态：是否已做过匹配分析、是否已向用户输出过文字
    did_analyze = False
    spoke = False
    try:
        for _ in range(_MAX_STEPS):
            final: dict | None = None
            for ev in llm.agent_stream(llm_messages, TOOLS, reasoning_effort):
                if ev["type"] == "reasoning":
                    # “关闭”时即使模型仍产出思考内容（如总是思考的 reasoner），也不展示
                    if reasoning_effort != "off":
                        yield ("reasoning", {"text": ev["text"]})
                elif ev["type"] == "delta":
                    spoke = True
                    yield ("delta", {"text": ev["text"]})
                elif ev["type"] == "tool_pending":
                    # 模型开始生成工具调用（参数可能较长且不可见）——立刻给出反馈填补空窗
                    yield ("status", {"phase": "tool", "message": _tool_pending_label(ev.get("name", ""))})
                elif ev["type"] == "final":
                    final = ev
            if final is None:
                break

            if final["finish"] == "tool_calls" and final["tool_calls"]:
                llm_messages.append(
                    {
                        "role": "assistant",
                        "content": final["content"] or None,
                        "tool_calls": [
                            {
                                "id": t["id"],
                                "type": "function",
                                "function": {"name": t["name"], "arguments": t["arguments"] or "{}"},
                            }
                            for t in final["tool_calls"]
                        ],
                    }
                )
                stop_turn = False
                for t in final["tool_calls"]:
                    # 硬性流程约束：匹配分析后【同一轮】不得直接生成学习计划，
                    # 必须先停下让用户回答关键问题（跨轮回答后才允许）。
                    if t["name"] == "generate_plan" and did_analyze:
                        llm_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": t["id"],
                                "content": (
                                    "本轮请先向用户提出关键问题并【停下等待用户在新消息中回答】，"
                                    "不要在 analyze_match 的同一轮内生成学习计划。"
                                ),
                            }
                        )
                        stop_turn = True
                        continue
                    if t["name"] == "analyze_match":
                        did_analyze = True
                    yield from _dispatch_tool(t, context, db, llm_messages, user_id)
                if stop_turn:
                    # 兜底：若本轮模型没说任何话（仅想直接生成计划），补上反问，避免对话卡住
                    if not spoke:
                        yield (
                            "delta",
                            {
                                "text": (
                                    "在生成学习路线前，想先了解几点：\n"
                                    "1) 你每周大概能投入多少小时？\n"
                                    "2) 距离目标到岗 / 截止还有几周？\n"
                                    "3) 偏好的学习方式（项目驱动 / 看视频 / 刷题）？\n"
                                    "4) 最想优先补强或深入哪些方向？\n"
                                    "5) 有没有可以改造、写进简历的现成项目？"
                                )
                            },
                        )
                    break
                continue  # 带着工具结果再让模型继续
            break
    except Exception as exc:  # noqa: BLE001
        yield ("error", {"message": f"对话生成失败：{exc}"})
        return

    yield ("done", {})


def _snippet(text: str, limit: int = 280) -> str:
    """把网页正文截断为摘要：超长时尽量在邻近空格处断开并加省略号，避免词中断裂。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > limit - 40:
        cut = cut[:sp]
    return cut.rstrip() + "…"


def _tool_pending_label(name: str) -> str:
    """模型开始生成某工具调用时，给用户的「准备中」提示。"""
    return {
        "analyze_match": "正在准备匹配分析…",
        "generate_plan": "正在准备生成学习计划…",
        "web_search": "正在准备联网检索…",
    }.get(name, "正在准备工具调用…")


def _dispatch_tool(
    tool: dict, context: dict, db: Session, llm_messages: list[dict], user_id: str = "local"
) -> Iterator[Event]:
    name = tool.get("name", "")
    tid = tool.get("id", "")
    try:
        args = json.loads(tool.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}

    if name == "web_search":
        query = str(args.get("query", "")).strip()
        yield ("tool_call", {"id": tid, "name": name, "label": f"联网搜索：{query}"})
        results, summary = search.web_search(query)
        # 把搜索结果【详情】显式发给前端（title/url/snippet），供其折叠展示。
        # 以 id 关联同一个 web_search 工具块；字段统一转字符串防御脏数据，snippet 按词边界截断。
        items = [
            {
                "title": str(r.get("title") or ""),
                "url": str(r.get("url") or ""),
                "snippet": _snippet(str(r.get("content") or "")),
            }
            for r in results
        ]
        # 仅在确有结果时下发（未配置 Tavily / 无结果时不发空事件，避免前端空折叠块）
        if items:
            yield ("search_results", {"id": tid, "query": query, "results": items})
        yield ("tool_result", {"id": tid, "name": name, "label": summary, "ok": bool(results)})
        llm_messages.append(
            {"role": "tool", "tool_call_id": tid, "content": search.results_to_text(query, results)}
        )
        return

    if name == "analyze_match":
        yield ("tool_call", {"id": tid, "name": name, "label": "运行匹配分析"})
        role = str(args.get("target_role") or context.get("target_role") or "").strip()

        # 取材：优先附件 context，其次模型在对话中提取并填入的工具参数
        resume_text = (context.get("resume_text") or args.get("resume_text") or "").strip()
        jd_texts = [t for t in (context.get("jd_texts") or []) if t and str(t).strip()]
        if not jd_texts and args.get("jd_texts"):
            jd_texts = [str(t) for t in args["jd_texts"] if t and str(t).strip()]

        extra = str(args.get("extra_jd") or "").strip()
        if extra:
            jd_texts = jd_texts + [f"{role or '该岗位'}行业常见技能要求（AI 联网整理）\n{extra}"]

        if not resume_text or not jd_texts:
            missing = "简历" if not resume_text else "目标岗位 JD"
            yield ("tool_result", {"id": tid, "name": name, "label": f"缺少{missing}", "ok": False})
            llm_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": (
                        f"无法分析：缺少{missing}。如果用户其实已在对话中提供，"
                        "请把内容原样填入 resume_text / jd_texts 参数后重试；否则简洁地请用户补充。"
                    ),
                }
            )
            return

        # 流式产出匹配分析子步骤进度（不含学习路线）
        weeks = int(context.get("weeks") or 4)
        outcome: dict | None = None
        for kind, payload in pipeline.analyze_match_streaming(resume_text, jd_texts, role):
            if kind == "status":
                yield ("status", {"phase": "analyzing", "message": payload})
            elif kind == "result":
                outcome = payload
        assert outcome is not None

        run = _persist_run(db, resume_text, jd_texts, outcome, role, weeks, user_id)
        result = outcome["result"]
        yield ("report", {"analysis_run_id": run.id, "result": result})
        yield ("tool_result", {"id": tid, "name": name, "label": f"匹配度 {result['match_score']}%", "ok": True})
        llm_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": _match_summary(result, run.id),
            }
        )
        return

    if name == "generate_plan":
        yield ("tool_call", {"id": tid, "name": name, "label": "生成学习计划"})
        # run_id 来源：模型参数优先，其次前端在 context 回传的最近一次分析 id
        run_id = args.get("analysis_run_id") or context.get("analysis_run_id")
        run = None
        if run_id is not None:
            try:
                run = db.get(AnalysisRun, int(run_id))
            except (TypeError, ValueError):
                run = None
        if run is None:
            yield ("tool_result", {"id": tid, "name": name, "label": "缺少匹配分析", "ok": False})
            llm_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": "找不到对应的匹配分析，请先在本轮调用 analyze_match 得到 analysis_run_id，再用它调用 generate_plan。",
                }
            )
            return

        prefs = {
            "weekly_hours": args.get("weekly_hours"),
            "focus_skills": args.get("focus_skills") or [],
            "learning_style": args.get("learning_style") or "",
        }
        weeks = int(args.get("timeline_weeks") or args.get("weeks") or run.weeks or 4)
        weeks = max(1, min(weeks, 12))

        yield ("status", {"phase": "planning", "message": "正在规划个性化学习路线…"})
        skill_gap = (run.result or {}).get("skill_gap", {})
        plan = pipeline.build_roadmap(skill_gap, weeks, run.target_role, prefs)

        # JSON 列须整体重新赋值，SQLAlchemy 才能侦测变更
        new_result = {**(run.result or {}), "roadmap": plan}
        run.result = new_result
        run.weeks = weeks
        db.commit()
        db.refresh(run)

        # 计划生成后把 roadmap 物化为可勾选 Task（旁路、失败降级「有报告无 Task」）
        _materialize_safe(db, run, user_id)

        yield ("report", {"analysis_run_id": run.id, "result": run.result})
        yield ("tool_result", {"id": tid, "name": name, "label": f"已生成 {weeks} 周计划", "ok": True})
        llm_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": (
                    f"已生成 {weeks} 周个性化学习路线并展示给用户。"
                    "请用中文简要说明计划思路与第 1 周重点，鼓励用户开始执行，并说明可随时调整。"
                ),
            }
        )
        return

    # 未知工具
    yield ("tool_result", {"id": tid, "name": name, "label": "未知工具", "ok": False})
    llm_messages.append({"role": "tool", "tool_call_id": tid, "content": f"未知工具：{name}"})


def _match_summary(result: dict, run_id: int) -> str:
    gaps = "、".join(g["name"] for g in result["skill_gap"]["must_have_gaps"][:4]) or "无明显必备缺口"
    strengths = "、".join(
        p["name"] for p in result["skill_gap"]["possessed"] if p.get("required_by")
    ) or "（待补充）"
    return (
        f"匹配分析已完成并展示给用户（analysis_run_id={run_id}）。匹配度 {result['match_score']}%；"
        f"必备技能缺口：{gaps}；岗位相关已具备：{strengths}。\n"
        "请用中文简要点出最该优先补的 1-3 项及原因（无需复述报告全文），"
        "然后【主动反问用户 2-4 个生成学习路线所需的关键信息】（每周可投入时长、距离到岗/截止周数、"
        "偏好学习方式、最想优先补强方向、是否有可改造项目）。等用户回答后，"
        f"再调用 generate_plan(analysis_run_id={run_id}, ...) 生成学习路线。此刻【不要】调用 generate_plan。"
    )


def _persist_run(
    db: Session,
    resume_text: str,
    jd_texts: list[str],
    outcome: dict,
    role: str,
    weeks: int,
    user_id: str = "local",
) -> AnalysisRun:
    resume_row = Resume(raw_text=resume_text, structured=outcome["resume"], source_type="chat")
    db.add(resume_row)
    db.flush()

    job_rows: list[JobPosting] = []
    for raw, structured in zip(jd_texts, outcome["parsed_jds"]):
        job = JobPosting(
            title=structured.get("title", ""),
            company=structured.get("company", ""),
            raw_text=raw,
            structured=structured,
        )
        db.add(job)
        job_rows.append(job)
    db.flush()

    run = AnalysisRun(
        resume_id=resume_row.id,
        job_ids=[j.id for j in job_rows],
        target_role=role,
        weeks=weeks,
        match_score=outcome["result"]["match_score"],
        result=outcome["result"],
        engine=outcome["engine"],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 物化有状态闭环。analyze_match 阶段 roadmap 为空→仅建 journey、0 Task；
    # 脚本化降级 / 完整分析 roadmap 非空→同时物化 Task。
    _materialize_safe(db, run, user_id)

    return run


# ---------------------------------------------------------------------------
# 脚本化降级（未启用 LLM 或非 openai 协议）
# ---------------------------------------------------------------------------


def _scripted_turn(context: dict, db: Session, user_id: str = "local") -> Iterator[Event]:
    resume_text = context.get("resume_text") or ""
    jd_texts = [t for t in (context.get("jd_texts") or []) if t and t.strip()]

    if not resume_text.strip():
        yield ("delta", {"text": "请先上传 PDF 简历或在输入框粘贴你的简历内容（教育背景、项目经历、技能等）。"})
        yield ("done", {})
        return
    if not jd_texts:
        yield ("delta", {"text": "请再添加至少一条目标岗位的 JD 原文，我就开始分析。建议 3~10 条更准。"})
        yield ("done", {})
        return

    yield ("status", {"phase": "analyzing", "message": "正在分析简历与 JD…"})
    role = context.get("target_role", "")
    weeks = int(context.get("weeks") or 4)
    outcome = pipeline.run_analysis(resume_text, jd_texts, role, weeks)
    run = _persist_run(db, resume_text, jd_texts, outcome, role, weeks, user_id)
    result = outcome["result"]
    yield ("report", {"analysis_run_id": run.id, "result": result})
    gaps = "、".join(g["name"] for g in result["skill_gap"]["must_have_gaps"][:3]) or "无明显必备缺口"
    yield (
        "delta",
        {
            "text": (
                f"分析完成：整体匹配度约 {result['match_score']}%，最该优先补强的是 {gaps}。"
                "（当前为规则模式，配置 LLM 后可获得联网检索与更深入的对话式解读。）"
            )
        },
    )
    yield ("done", {})
