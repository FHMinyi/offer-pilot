"""技能归一化（PRD §7.3）。

把 JD / 简历文本里的各种写法统一到技能本体的规范节点上，
并保留命中的原始词作为“来源证据”。
"""

from __future__ import annotations

import re

from ..data.skills import CATEGORIES, SKILL_BY_KEY, SKILL_TREE, SKILLS

# 判断 alias 是否为纯 ASCII（英文/数字/符号），用于决定匹配策略
_ASCII_RE = re.compile(r"^[\x00-\x7f]+$")


def _is_ascii(text: str) -> bool:
    return bool(_ASCII_RE.match(text))


def _build_alias_index() -> list[tuple[str, str, re.Pattern | None]]:
    """构建 (skill_key, alias, 预编译正则或 None) 列表。

    英文别名用“非字母数字边界”正则，避免 ts 命中 tests、go 命中 good 之类误匹配；
    中文别名用子串匹配（编译为 None，调用方走 `in`）。
    """
    index: list[tuple[str, str, re.Pattern | None]] = []
    for skill in SKILLS:
        # 别名 + 规范名都纳入匹配
        terms = set(skill["aliases"]) | {skill["name"]}
        for term in terms:
            t = term.lower().strip()
            if not t:
                continue
            if _is_ascii(t):
                pattern = re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
                index.append((skill["key"], term, pattern))
            else:
                index.append((skill["key"], term, None))
    return index


_ALIAS_INDEX = _build_alias_index()


def match_skills(text: str) -> dict[str, list[str]]:
    """在文本中匹配技能。

    返回 {skill_key: [命中的原始词, ...]}，命中词可作为来源证据展示。
    """
    if not text:
        return {}
    lowered = text.lower()
    hits: dict[str, set[str]] = {}
    for key, term, pattern in _ALIAS_INDEX:
        matched = pattern.search(lowered) if pattern else (term.lower() in lowered)
        if matched:
            hits.setdefault(key, set()).add(term)
    # set 转排序 list，保证输出稳定
    return {k: sorted(v) for k, v in hits.items()}


def _freeform_key(term: str) -> str:
    """未收录技能的稳定 key：小写 + 压缩空白，保证不同写法尽量归并。"""
    return re.sub(r"\s+", " ", term.strip().lower())


def normalize_terms(terms: list[str]) -> list[dict]:
    """把候选技能词归一化为技能列表。

    - 能匹配技能本体的：归一到规范节点（含别名分组，如 TS→TypeScript）。
    - 匹配不到的（新兴/未收录技能，如某些新框架）：保留为 free-form，以原词为名，
      category 记为「其他」，key 用规范化原词——这样联网搜到 / JD 提到的新兴技能
      也能进入缺口分析与路线，而不会被固定本体过滤掉。
    """
    result: dict[str, dict] = {}
    for raw in terms or []:
        term = str(raw).strip()
        if not term:
            continue
        matched = match_skills(term)
        if matched:
            for key, evid in matched.items():
                node = result.setdefault(
                    key,
                    {"key": key, "name": skill_name(key), "category": skill_category(key), "evidence": []},
                )
                node["evidence"].extend(evid or [term])
        else:
            key = _freeform_key(term)
            if not key:
                continue
            node = result.setdefault(key, {"key": key, "name": term, "category": "其他", "evidence": []})
            node["evidence"].append(term)
    for node in result.values():
        node["evidence"] = dedup_evidence(node["evidence"])
    return sorted(result.values(), key=lambda x: x["name"])


def dedup_evidence(terms: list[str]) -> list[str]:
    """对命中的证据词做大小写去重（如 Git / git 合并为一个），保持稳定排序。"""
    seen: dict[str, str] = {}
    for t in terms:
        low = t.lower()
        if low not in seen:
            seen[low] = t
    return sorted(seen.values())


def skill_name(key: str) -> str:
    s = SKILL_BY_KEY.get(key)
    return s["name"] if s else key


def skill_category(key: str) -> str:
    s = SKILL_BY_KEY.get(key)
    return s["category"] if s else "通用"


def build_graph() -> dict:
    """构建技能图谱（供 /api/skills/graph）。"""
    categories = []
    for cat in CATEGORIES:
        keys = SKILL_TREE.get(cat, [])
        nodes = [
            {"key": k, "name": SKILL_BY_KEY[k]["name"]}
            for k in keys
            if k in SKILL_BY_KEY
        ]
        if nodes:
            categories.append({"category": cat, "skills": nodes})
    return {
        "proficiency_levels": ["了解", "熟悉", "掌握", "精通"],
        "categories": categories,
    }
