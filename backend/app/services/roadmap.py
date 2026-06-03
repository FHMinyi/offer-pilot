"""学习 / 面试准备路线生成（PRD §7.5）。

把缺口技能按优先级分配到每一周，并为每周给出：
学什么、做什么练习、产出什么、如何自检（兼面试准备重点）。
这里采用确定性的规则编排（基于技能本体的学习模板），保证结果稳定可执行。
"""

from __future__ import annotations

import math

from ..data.skills import SKILL_BY_KEY


def generate(gap: dict, weeks: int, target_role: str, prefs: dict | None = None) -> list[dict]:
    """生成按周拆分的路线。

    gap:   gap_analysis.analyze 的结果（或 result["skill_gap"]）
    weeks: 总周数（1~12）
    prefs: 可选用户偏好——{weekly_hours:int, focus_skills:[技能名], learning_style:str}
    """
    prefs = prefs or {}
    weeks = max(1, min(weeks, 12))
    role = target_role or "目标岗位"
    weekly_hours = prefs.get("weekly_hours")
    focus = {str(f) for f in (prefs.get("focus_skills") or [])}

    # 优先级队列：必备缺口（已按优先级排序）在前，加分缺口在后
    queue: list[dict] = list(gap.get("must_have_gaps", [])) + list(gap.get("nice_to_have_gaps", []))

    # 用户指定的“最想优先补强”的技能稳定提前
    if focus:
        queue.sort(key=lambda g: 0 if g.get("name") in focus else 1)

    if not queue:
        return _no_gap_roadmap(gap, weeks, role, weekly_hours)

    # 每周聚焦技能数：时间充裕(>=12h)可到 2，时间紧(<8h)收敛到 1
    per_week = _per_week(len(queue), weeks, weekly_hours)
    plan: list[dict] = []
    idx = 0
    for w in range(1, weeks + 1):
        chunk = queue[idx : idx + per_week]
        idx += per_week
        if not chunk and plan:
            # 技能已分配完，剩余周用于复盘 + 面试冲刺
            plan.append(_review_week(w, gap, role, last=(w == weeks), weekly_hours=weekly_hours))
            continue
        plan.append(_skill_week(w, chunk, role, last=(w == weeks), weekly_hours=weekly_hours))

    # 若技能没分配完（技能数 > per_week*weeks），把剩余并入最后一周
    if idx < len(queue):
        leftover = queue[idx:]
        _merge_leftover(plan[-1], leftover)

    return plan


def _per_week(num_skills: int, weeks: int, weekly_hours: int | None = None) -> int:
    base = max(1, min(2, math.ceil(num_skills / weeks)))
    if weekly_hours:
        if weekly_hours < 8:
            return 1
        if weekly_hours >= 12:
            return min(2, base if base >= 2 else 2)
    return base


def _skill_week(
    week: int, chunk: list[dict], role: str, last: bool, weekly_hours: int | None = None
) -> dict:
    focus_skills: list[str] = []
    tasks: list[str] = []
    deliverables: list[str] = []
    interview_focus: list[str] = []

    for gapitem in chunk:
        key = gapitem["key"]
        name = gapitem["name"]
        focus_skills.append(name)
        meta = SKILL_BY_KEY.get(key, {})
        learn = meta.get("learn", [f"系统学习 {name} 的核心知识点"])
        check = meta.get("check", f"能清晰讲解 {name} 的核心概念")
        tasks.extend(learn)
        deliverables.append(f"产出与「{name}」相关的练习/笔记或小 demo")
        interview_focus.append(check)

    # 每周固定动作：把学到的内容反哺到简历表达
    deliverables.append("更新简历中相关项目的描述，体现本周所学")

    # 有用户每周可投入时长则以其为准（限定合理区间），否则按技能数估算
    if weekly_hours:
        hours = max(4, min(int(weekly_hours), 40))
    else:
        hours = 8 * len(chunk) + 3  # 每个技能约 8h + 复习缓冲

    if last:
        tasks.append("整理本阶段成果，做一次自我模拟面试")
        interview_focus.append("准备自我介绍与项目深挖问答")

    return {
        "week": week,
        "focus_skills": focus_skills,
        "tasks": tasks,
        "deliverables": deliverables,
        "estimated_hours": hours,
        "interview_focus": interview_focus,
    }


def _review_week(week: int, gap: dict, role: str, last: bool, weekly_hours: int | None = None) -> dict:
    """技能已学完后的复盘 / 面试冲刺周。"""
    top = [g["name"] for g in gap.get("must_have_gaps", [])[:3]]
    focus = top or [p["name"] for p in gap.get("possessed", [])[:3]]
    hours = max(4, min(int(weekly_hours), 40)) if weekly_hours else 12
    return {
        "week": week,
        "focus_skills": focus,
        "tasks": [
            "复盘前几周的薄弱点，针对性查漏补缺",
            f"按{role}高频面试题做专项练习",
            "重写并打磨简历，确保每条经历都能讲清",
        ],
        "deliverables": ["一份可投递的简历终稿", "一份高频面试题问答整理"],
        "estimated_hours": hours,
        "interview_focus": ["完整模拟一轮技术面", "复盘并优化项目讲述话术"],
    }


def _merge_leftover(week_item: dict, leftover: list[dict]) -> None:
    names = [g["name"] for g in leftover]
    week_item["focus_skills"].extend(names)
    week_item["tasks"].append("利用机动时间补齐以下技能：" + "、".join(names))
    week_item["estimated_hours"] += 4 * len(leftover)


def _no_gap_roadmap(gap: dict, weeks: int, role: str, weekly_hours: int | None = None) -> list[dict]:
    """无明显缺口时，路线转向深化与面试冲刺。"""
    strengths = [p["name"] for p in gap.get("possessed", [])[:4]]
    hours = max(4, min(int(weekly_hours), 40)) if weekly_hours else 10
    plan: list[dict] = []
    for w in range(1, weeks + 1):
        last = w == weeks
        plan.append(
            {
                "week": w,
                "focus_skills": strengths[: max(1, len(strengths))] if w == 1 else strengths[:2],
                "tasks": (
                    ["深化已有技能的底层原理，能讲清“为什么”", f"按{role}方向做项目深挖与扩展"]
                    if not last
                    else ["全流程模拟面试并复盘", "打磨简历与项目话术"]
                ),
                "deliverables": ["一篇技术原理总结或项目复盘"]
                if not last
                else ["简历终稿", "面试问答整理"],
                "estimated_hours": hours,
                "interview_focus": ["项目深挖问答"] if not last else ["完整模拟一轮技术面"],
            }
        )
    return plan
