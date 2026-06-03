"""技能缺口分析（PRD §7.4）。

对比简历技能与 JD 必备/加分技能，输出：
- 必备技能缺口（缺失 / 薄弱）
- 加分技能缺口
- 已具备技能
- 匹配度评分

每个结论都带来源说明：该技能来自哪几份 JD、简历里哪段经历支持了它、为什么判为缺失/薄弱。
"""

from __future__ import annotations

import math


def _priority(frequency: int, num_jds: int, is_must: bool) -> str:
    ratio = frequency / num_jds if num_jds else 0
    if ratio >= 0.6:
        level = "高"
    elif ratio >= 0.3:
        level = "中"
    else:
        level = "低"
    # 加分技能优先级最高封顶为“中”
    if not is_must and level == "高":
        level = "中"
    return level


def _aggregate(parsed_jds: list[dict], field: str) -> dict[str, dict]:
    """聚合多份 JD 的某类技能（must_have / nice_to_have）。

    返回 {key: {name, category, frequency, required_by:[JD标题]}}。
    """
    agg: dict[str, dict] = {}
    for jd in parsed_jds:
        title = jd.get("title") or "未命名岗位"
        for skill in jd.get(field, []):
            key = skill["key"]
            node = agg.setdefault(
                key,
                {
                    "key": key,
                    "name": skill["name"],
                    "category": skill["category"],
                    "frequency": 0,
                    "required_by": [],
                },
            )
            node["frequency"] += 1
            if title not in node["required_by"]:
                node["required_by"].append(title)
    return agg


def analyze(resume: dict, parsed_jds: list[dict]) -> dict:
    """执行缺口分析。

    resume:    parse_resume 的结果（含 skills 列表）
    parsed_jds: parse_jd 的结果列表
    """
    num_jds = max(len(parsed_jds), 1)

    # 简历技能索引：key -> {name, category, evidence}
    resume_skills = {s["key"]: s for s in resume.get("skills", [])}

    # 项目经历中出现的技能 = 强证据
    project_keys = _project_skill_keys(resume)

    must_agg = _aggregate(parsed_jds, "must_have")
    nice_agg = _aggregate(parsed_jds, "nice_to_have")

    must_have_gaps: list[dict] = []
    nice_to_have_gaps: list[dict] = []
    weak_must_keys: set[str] = set()

    # ---- 必备技能 ----
    strong_have = 0.0
    for key, node in must_agg.items():
        if key in resume_skills:
            # 强证据 = 有项目/实习经历支撑；仅出现在“技能罗列”中则视为薄弱
            strong = key in project_keys
            if strong:
                strong_have += 1.0
            else:
                strong_have += 0.5
                weak_must_keys.add(key)
                must_have_gaps.append(
                    {
                        **_base_gap(node, num_jds, is_must=True),
                        "gap_level": "薄弱",
                        "reason": (
                            f"{node['frequency']} 个目标 JD 要求该技能；"
                            "简历中有提及但证据较弱（多为技能罗列、缺少项目支撑），"
                            "建议用具体项目经历强化表达。"
                        ),
                    }
                )
        else:
            must_have_gaps.append(
                {
                    **_base_gap(node, num_jds, is_must=True),
                    "gap_level": "缺失",
                    "reason": f"{node['frequency']} 个目标 JD 要求该技能，简历中未发现相关证据。",
                }
            )

    # ---- 加分技能 ----
    for key, node in nice_agg.items():
        if key in must_agg:
            continue  # 已在必备里体现
        if key not in resume_skills:
            nice_to_have_gaps.append(
                {
                    **_base_gap(node, num_jds, is_must=False),
                    "gap_level": "缺失",
                    "reason": f"{node['frequency']} 个目标 JD 将其列为加分项，掌握后更有竞争力。",
                }
            )

    # ---- 已具备技能（排除被判为薄弱的必备技能，避免自相矛盾）----
    possessed = _build_possessed(resume_skills, must_agg, nice_agg, weak_must_keys)

    # ---- 匹配度评分 ----
    match_score = _score(must_agg, nice_agg, strong_have, resume_skills)

    # 排序：必备缺口按 优先级(高>中>低) -> 频次 降序
    order = {"高": 0, "中": 1, "低": 2}
    must_have_gaps.sort(key=lambda g: (order[g["priority"]], -g["frequency"]))
    nice_to_have_gaps.sort(key=lambda g: -g["frequency"])

    return {
        "match_score": match_score,
        "must_have_gaps": must_have_gaps,
        "nice_to_have_gaps": nice_to_have_gaps,
        "possessed": possessed,
    }


def _base_gap(node: dict, num_jds: int, is_must: bool) -> dict:
    return {
        "key": node["key"],
        "name": node["name"],
        "category": node["category"],
        "required_by": node["required_by"],
        "frequency": node["frequency"],
        "priority": _priority(node["frequency"], num_jds, is_must),
    }


def _project_skill_keys(resume: dict) -> set[str]:
    """从项目经历里抽取技能 key，作为强证据来源。"""
    from . import skills as skills_svc

    text_parts: list[str] = []
    for proj in resume.get("projects", []):
        text_parts.append(str(proj.get("title", "")))
        text_parts.append(str(proj.get("description", "")))
        text_parts.extend(proj.get("tech", []) or [])
    for exp in resume.get("experiences", []):
        text_parts.append(str(exp.get("description", "")))
    return set(skills_svc.match_skills("\n".join(text_parts)).keys())


def _build_possessed(
    resume_skills: dict[str, dict],
    must_agg: dict[str, dict],
    nice_agg: dict[str, dict],
    weak_must_keys: set[str],
) -> list[dict]:
    possessed: list[dict] = []
    for key, s in resume_skills.items():
        if key in weak_must_keys:
            continue
        required_by: list[str] = []
        if key in must_agg:
            required_by = list(must_agg[key]["required_by"])
        elif key in nice_agg:
            required_by = list(nice_agg[key]["required_by"])
        possessed.append(
            {
                "key": key,
                "name": s["name"],
                "category": s["category"],
                "evidence": s.get("evidence", []),
                "required_by": required_by,
            }
        )
    # 与目标岗位相关的（required_by 非空）排前面
    possessed.sort(key=lambda p: (0 if p["required_by"] else 1, p["name"]))
    return possessed


def _score(
    must_agg: dict[str, dict],
    nice_agg: dict[str, dict],
    strong_have: float,
    resume_skills: dict[str, dict],
) -> int:
    """计算匹配度（0-100），强证据计 1 分、弱证据计 0.5 分。"""
    nice_keys = [k for k in nice_agg if k not in must_agg]

    if must_agg:
        must_score = strong_have / len(must_agg)
    else:
        # 无明确必备技能时，用“简历技能与加分技能的覆盖”兜底
        must_score = 0.6

    if nice_keys:
        nice_have = sum(1 for k in nice_keys if k in resume_skills)
        nice_score = nice_have / len(nice_keys)
        final = 0.8 * must_score + 0.2 * nice_score
    else:
        final = must_score

    return max(0, min(100, math.floor(final * 100 + 0.5)))
