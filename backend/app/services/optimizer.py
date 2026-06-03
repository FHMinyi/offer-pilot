"""简历 / 项目表达优化建议（PRD §7 / §6）。

基于缺口分析与简历结构，给出“哪些经历应强化、补证据或重写表达”的具体建议。
优先 LLM，未配置时降级为规则生成。建议尽量具体、可执行，避免空话。
"""

from __future__ import annotations

import json

from . import llm


def suggest(resume: dict, gap: dict, parsed_jds: list[dict], target_role: str) -> list[dict]:
    """返回 [{title, detail, related_skills:[技能名]}]。"""
    try:
        return _suggest_with_llm(resume, gap, parsed_jds, target_role)
    except llm.LLMUnavailable:
        return _suggest_with_rules(resume, gap, target_role)


# ---------------------------------------------------------------------------
# LLM 模式
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """你是资深技术求职辅导老师。基于学生简历结构与岗位缺口分析，
给出 3~6 条具体、可执行的简历/项目表达优化建议（不要空话，要落到“怎么改”）。
输出 JSON：{"suggestions": [{"title": "...", "detail": "...", "related_skills": ["..."]}]}。
detail 要说明改前问题与改后方向，可给出可量化表达示例。只输出 JSON。"""


def _suggest_with_llm(resume: dict, gap: dict, parsed_jds: list[dict], target_role: str) -> list[dict]:
    payload = {
        "target_role": target_role,
        "resume": {
            "projects": resume.get("projects", []),
            "experiences": resume.get("experiences", []),
            "skills": [s["name"] for s in resume.get("skills", [])],
        },
        "must_have_gaps": [
            {"name": g["name"], "gap_level": g["gap_level"], "priority": g["priority"]}
            for g in gap.get("must_have_gaps", [])
        ],
    }
    data = llm.complete_json(_LLM_SYSTEM, json.dumps(payload, ensure_ascii=False))
    suggestions = data.get("suggestions", [])
    out = []
    for s in suggestions[:6]:
        out.append(
            {
                "title": str(s.get("title", "")).strip(),
                "detail": str(s.get("detail", "")).strip(),
                "related_skills": list(s.get("related_skills", [])),
            }
        )
    return out or _suggest_with_rules(resume, gap, target_role)


# ---------------------------------------------------------------------------
# 规则模式
# ---------------------------------------------------------------------------


def _suggest_with_rules(resume: dict, gap: dict, target_role: str) -> list[dict]:
    suggestions: list[dict] = []
    role = target_role or "目标岗位"

    weak = [g for g in gap.get("must_have_gaps", []) if g["gap_level"] == "薄弱"]
    missing = [g for g in gap.get("must_have_gaps", []) if g["gap_level"] == "缺失"]
    projects = resume.get("projects", [])

    # 1) 薄弱必备技能：下沉到项目，补可验证证据
    if weak:
        names = [g["name"] for g in weak[:3]]
        suggestions.append(
            {
                "title": f"把「{ '、'.join(names) }」从技能罗列下沉到项目描述",
                "detail": (
                    "这些技能在简历中只是被列出，缺少项目支撑，面试官难以判断真实水平。"
                    "建议在相关项目里补一句“使用 X 解决了什么问题、带来什么可量化结果”，"
                    "例如“用 TypeScript 重构核心模块，类型错误减少约 N%”。"
                ),
                "related_skills": names,
            }
        )

    # 2) 高优先级缺失技能：用一个小项目补齐
    high_missing = [g for g in missing if g["priority"] == "高"]
    if high_missing:
        names = [g["name"] for g in high_missing[:3]]
        suggestions.append(
            {
                "title": f"针对高频要求补一个体现「{ '、'.join(names) }」的小项目",
                "detail": (
                    f"这些技能被多数{role} JD 列为必备但简历中缺失。"
                    "建议做一个 1~2 周可完成的小项目并写进简历，"
                    "突出你用到的技术点、负责的模块与最终产出，而不是只写“学习了 X”。"
                ),
                "related_skills": names,
            }
        )

    # 3) 项目缺少量化结果
    if projects:
        suggestions.append(
            {
                "title": "为项目补充可量化结果与个人贡献",
                "detail": (
                    "用 STAR（情境-任务-行动-结果）重写项目描述，"
                    "把“做了什么”改写为“解决了什么问题、用了什么技术、带来什么可量化结果”，"
                    "并明确区分团队成果与你个人负责的部分。"
                ),
                "related_skills": [],
            }
        )
    else:
        # 没有可识别的项目经历
        suggestions.append(
            {
                "title": "补充至少一个与目标岗位相关的项目经历",
                "detail": (
                    f"当前简历未能识别出清晰的项目经历，而{role}非常看重项目落地能力。"
                    "建议把课程设计、个人项目或比赛经历结构化成项目条目，"
                    "包含背景、你的角色、技术栈和成果。"
                ),
                "related_skills": [],
            }
        )

    # 4) 已具备但未与岗位对齐的技能：在简历中前置呈现
    possessed_relevant = [p for p in gap.get("possessed", []) if p.get("required_by")]
    if possessed_relevant:
        names = [p["name"] for p in possessed_relevant[:4]]
        suggestions.append(
            {
                "title": "把岗位强相关的已有技能在简历中前置呈现",
                "detail": (
                    f"你已具备 { '、'.join(names) } 等岗位要求的技能，"
                    "建议把它们放到简历靠前位置或技能栏首行，并在项目里点明，"
                    "让筛选简历的人一眼看到匹配点。"
                ),
                "related_skills": names,
            }
        )

    # 5) 通用：面试表达
    suggestions.append(
        {
            "title": "准备每段项目的一句话亮点与深挖问答",
            "detail": (
                "为每个核心项目准备“一句话亮点 + 3 个可能被追问的技术点”，"
                "确保能从需求、设计、难点、结果四个角度讲清楚，避免被一问就卡壳。"
            ),
            "related_skills": [],
        }
    )

    return suggestions[:6]
