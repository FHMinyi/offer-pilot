"""分析工作流编排（PRD §10.1）。

把各节点按顺序串成一个可控工作流（而非自由 Agent）：
简历解析 → JD 解析 → 技能归一化 → 缺口分析 → 简历优化 → 路线生成 → 结果整理。

本模块不直接接触数据库，返回纯数据，便于上层路由按需持久化与测试。
"""

from __future__ import annotations

import concurrent.futures as cf
from collections.abc import Iterator

from . import gap_analysis, jd_parser, llm, optimizer, resume_parser, roadmap


def run_analysis(
    resume_text: str,
    jd_texts: list[str],
    target_role: str = "",
    weeks: int = 4,
) -> dict:
    """执行一次完整分析，返回中间产物与最终结果（阻塞式，内部复用流式实现）。

    返回：
    {
      "engine": str,            # rule / llm:openai / llm:anthropic
      "resume": dict,           # 结构化简历
      "parsed_jds": [dict],     # 结构化 JD（含 must/nice 技能）
      "result": dict,           # 符合前后端契约的 AnalysisResult
    }
    """
    outcome: dict | None = None
    for kind, payload in run_analysis_streaming(resume_text, jd_texts, target_role, weeks):
        if kind == "result":
            outcome = payload
    assert outcome is not None
    return outcome


def _parse_inputs_streaming(resume_text: str, jd_texts: list[str]) -> Iterator[tuple[str, object]]:
    """并发解析简历与各 JD（多路 LLM 调用并行），按完成进度产出 status。

    最后产出 ("parsed", (resume, parsed_jds))。
    LLM 模式下解析是耗时大头，线程池并发可显著缩短总时长。
    """
    n = len(jd_texts)
    yield ("status", (f"正在并行解析简历与 {n} 条 JD…" if n else "正在解析简历…"))

    with cf.ThreadPoolExecutor(max_workers=min(6, 1 + n)) as ex:
        resume_future = ex.submit(resume_parser.parse_resume, resume_text)
        jd_futures = {ex.submit(jd_parser.parse_jd, t): i for i, t in enumerate(jd_texts)}
        parsed_jds: list[dict] = [None] * n  # type: ignore[list-item]
        done = 0
        for fut in cf.as_completed(jd_futures):
            idx = jd_futures[fut]
            jd = fut.result()
            parsed_jds[idx] = jd
            done += 1
            # 每条 JD 解析完成时，附带其标题与抽取到的必备/加分技能，便于前端展示逐条分析过程
            yield ("status", f"已解析 {done}/{n} · {_jd_brief(jd)}")
        resume = resume_future.result()

    # 简历解析完成后也给出识别到的技能，作为过程的一部分
    rskills = "、".join(s["name"] for s in resume.get("skills", [])[:6]) or "—"
    yield ("status", f"简历解析完成 · 识别技能：{rskills}")

    yield ("parsed", (resume, parsed_jds))


def _jd_brief(jd: dict) -> str:
    """把一条解析后的 JD 概述为一行：标题 + 必备/加分技能。"""
    title = jd.get("title") or "未命名岗位"
    must = "、".join(s["name"] for s in jd.get("must_have", [])[:5]) or "—"
    nice = "、".join(s["name"] for s in jd.get("nice_to_have", [])[:5]) or "—"
    return f"「{title}」必备：{must}；加分：{nice}"


def analyze_match_streaming(
    resume_text: str,
    jd_texts: list[str],
    target_role: str = "",
) -> Iterator[tuple[str, object]]:
    """第一阶段：匹配度 + 岗位画像 + 技能缺口 + 简历优化建议（不含学习路线）。

    产出 ("status", str) 进度，最后 ("result", outcome)，其中 outcome["result"]["roadmap"] 为空。
    """
    jd_texts = [t for t in (jd_texts or []) if t and t.strip()]

    resume: dict = {}
    parsed_jds: list[dict] = []
    for kind, payload in _parse_inputs_streaming(resume_text, jd_texts):
        if kind == "status":
            yield ("status", payload)
        elif kind == "parsed":
            resume, parsed_jds = payload  # type: ignore[assignment]

    yield ("status", "正在分析技能缺口…")
    gap = gap_analysis.analyze(resume, parsed_jds)

    yield ("status", "正在生成简历优化建议…")
    suggestions = optimizer.suggest(resume, gap, parsed_jds, target_role)

    job_profile = _build_job_profile(parsed_jds)
    match_score = gap["match_score"]
    summary = _build_summary(match_score, gap, target_role, len(parsed_jds))
    engine = llm.engine_name()

    result = {
        "match_score": match_score,
        "summary": summary,
        "engine": engine,
        "target_role": target_role,
        "job_profile": job_profile,
        "skill_gap": {
            "must_have_gaps": gap["must_have_gaps"],
            "nice_to_have_gaps": gap["nice_to_have_gaps"],
            "possessed": gap["possessed"],
        },
        "resume_suggestions": suggestions,
        "roadmap": [],  # 学习路线在第二阶段（收集用户偏好后）生成
    }

    yield ("result", {"engine": engine, "resume": resume, "parsed_jds": parsed_jds, "result": result})


def build_roadmap(skill_gap: dict, weeks: int, target_role: str, prefs: dict | None = None) -> list[dict]:
    """第二阶段：基于已得缺口与用户偏好生成学习路线。

    skill_gap 形如 result["skill_gap"]（含 must_have_gaps / nice_to_have_gaps / possessed）。
    """
    return roadmap.generate(skill_gap, weeks, target_role, prefs)


def run_analysis_streaming(
    resume_text: str,
    jd_texts: list[str],
    target_role: str = "",
    weeks: int = 4,
) -> Iterator[tuple[str, object]]:
    """完整分析（匹配 + 学习路线一次产出）。供脚本降级与既有接口复用。

    逐步 yield ("status", str)，最后一次 ("result", outcome)。
    """
    outcome: dict | None = None
    for kind, payload in analyze_match_streaming(resume_text, jd_texts, target_role):
        if kind == "status":
            yield ("status", payload)
        elif kind == "result":
            outcome = payload  # type: ignore[assignment]
    assert outcome is not None

    yield ("status", "正在规划学习路线…")
    outcome["result"]["roadmap"] = build_roadmap(
        outcome["result"]["skill_gap"], weeks, target_role
    )
    yield ("result", outcome)


def _skill_ref(skill: dict) -> dict:
    """把解析得到的技能裁剪为契约里的 SkillRef。"""
    return {"key": skill["key"], "name": skill["name"], "category": skill["category"]}


def _build_job_profile(parsed_jds: list[dict]) -> dict:
    """聚合多份 JD 形成岗位画像。"""
    titles: list[str] = []
    responsibilities: list[str] = []
    requirements: list[str] = []
    tech_stack: list[str] = []
    jobs: list[dict] = []

    for jd in parsed_jds:
        title = jd.get("title") or "未命名岗位"
        if title not in titles:
            titles.append(title)
        responsibilities.extend(jd.get("responsibilities", []))
        requirements.extend(jd.get("requirements", []))
        for s in jd.get("must_have", []) + jd.get("nice_to_have", []):
            if s["name"] not in tech_stack:
                tech_stack.append(s["name"])
        jobs.append(
            {
                "title": title,
                "company": jd.get("company", ""),
                "responsibilities": jd.get("responsibilities", []),
                "requirements": jd.get("requirements", []),
                "must_have": [_skill_ref(s) for s in jd.get("must_have", [])],
                "nice_to_have": [_skill_ref(s) for s in jd.get("nice_to_have", [])],
            }
        )

    return {
        "titles": titles,
        "responsibilities": _dedup(responsibilities)[:12],
        "requirements": _dedup(requirements)[:10],
        "tech_stack": tech_stack[:30],
        "jobs": jobs,
    }


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def _build_summary(score: int, gap: dict, target_role: str, num_jds: int) -> str:
    role = target_role or "目标岗位"
    top_gaps = [g["name"] for g in gap.get("must_have_gaps", [])[:3]]
    strengths = [p["name"] for p in gap.get("possessed", []) if p.get("required_by")][:3]

    parts = [f"针对「{role}」，综合 {num_jds} 份 JD 分析，整体匹配度约 {score}%。"]
    if top_gaps:
        parts.append("最需优先补强：" + "、".join(top_gaps) + "。")
    else:
        parts.append("必备技能覆盖良好，建议把重点放在项目深化与面试表达上。")
    if strengths:
        parts.append("你已具备的相关优势：" + "、".join(strengths) + "。")
    return "".join(parts)
