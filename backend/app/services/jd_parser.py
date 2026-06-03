"""JD 解析（PRD §7.2）。

把岗位描述拆成可比较的结构：职位名、职责、必备/加分技能、学历年级要求、技术栈。
优先 LLM，未配置时降级为规则解析。
"""

from __future__ import annotations

import re

from . import llm, skills

# 必备技能上下文线索词
_MUST_CUES = ["精通", "熟练", "扎实", "必须", "要求", "掌握", "具备", "熟悉"]
# 加分技能上下文线索词
_NICE_CUES = ["加分", "优先", "更佳", "更好", "者优先", "了解", "bonus", "plus", "nice to have", "有.*经验者"]

# 职责段 / 要求段标题线索
_RESP_HEADERS = ["岗位职责", "工作职责", "职责", "你将", "responsibilities", "what you'll do"]
_REQ_HEADERS = ["任职要求", "岗位要求", "任职资格", "要求", "我们希望", "requirements", "qualifications"]

# 学历 / 年级 / 实习周期线索
_DEGREE_RE = re.compile(r"(本科|硕士|研究生|博士|大专|学历)")
_GRADE_RE = re.compile(r"(应届|往届|大[一二三四]|研[一二三]|在校|毕业生|\d{4}\s*届)")
_INTERN_RE = re.compile(r"(实习|到岗|出勤|每周|一周|\d\s*天/?周|\d\s*个月|长期|转正)")


def parse_jd(raw_text: str) -> dict:
    """解析单条 JD，返回结构化 dict。"""
    try:
        data = _parse_with_llm(raw_text)
    except llm.LLMUnavailable:
        data = _parse_with_rules(raw_text)

    # 统一用本体归一化 must / nice 技能，保证缺口分析口径一致
    data["must_have"] = _normalize(data.get("_must_terms"), raw_text, default_all=True)
    data["nice_have_raw"] = data.get("nice_have_raw")
    data["nice_to_have"] = _normalize(data.get("_nice_terms"), raw_text, default_all=False)
    # nice 与 must 去重：同一技能若已在 must，则从 nice 移除
    must_keys = {s["key"] for s in data["must_have"]}
    data["nice_to_have"] = [s for s in data["nice_to_have"] if s["key"] not in must_keys]

    data.pop("_must_terms", None)
    data.pop("_nice_terms", None)
    data.pop("nice_have_raw", None)
    return data


# ---------------------------------------------------------------------------
# LLM 模式
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """你是岗位 JD 结构化解析器。请把 JD 解析为 JSON：
- title: 职位名称
- company: 公司名（无则空字符串）
- responsibilities: 字符串数组（岗位职责要点）
- requirements: 字符串数组（学历/年级/实习周期等硬性要求）
- tech_stack: 字符串数组（涉及的技术栈/工具，原文写法）
- must_have: 字符串数组（必备技能词）
- nice_to_have: 字符串数组（加分技能词）
只输出 JSON。"""


def _parse_with_llm(raw_text: str) -> dict:
    # 单条 JD 解析用 jd 角色模型（可配置为更快的小模型，多条并发更省时）
    data = llm.complete_json(_LLM_SYSTEM, raw_text, model=llm.model_for("jd"))
    return {
        "title": str(data.get("title", "")).strip(),
        "company": str(data.get("company", "")).strip(),
        "responsibilities": list(data.get("responsibilities", [])),
        "requirements": list(data.get("requirements", [])),
        "tech_stack": list(data.get("tech_stack", [])),
        "_must_terms": list(data.get("must_have", [])) + list(data.get("tech_stack", [])),
        "_nice_terms": list(data.get("nice_to_have", [])),
    }


# ---------------------------------------------------------------------------
# 规则模式
# ---------------------------------------------------------------------------


def _parse_with_rules(raw_text: str) -> dict:
    title = _extract_title(raw_text)
    company = _extract_company(raw_text)
    responsibilities, requirements = _split_resp_req(raw_text)

    # 逐行判定每个技能命中所处上下文是必备还是加分
    must_lines, nice_lines = _classify_lines(raw_text)
    must_terms = _collect_terms(must_lines)
    nice_terms = _collect_terms(nice_lines)

    reqs = _extract_requirements(raw_text)
    if requirements:
        reqs = list(dict.fromkeys(requirements + reqs))

    return {
        "title": title,
        "company": company,
        "responsibilities": responsibilities,
        "requirements": reqs,
        "tech_stack": [],  # 规则模式不单独抽取，技能已并入 must/nice
        "_must_terms": must_terms,
        "_nice_terms": nice_terms,
    }


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # 含典型岗位关键词的行优先
        if re.search(r"(实习|工程师|开发|岗|developer|engineer|intern)", s, re.I):
            return s[:60]
        return s[:60]
    return "未命名岗位"


def _extract_company(text: str) -> str:
    m = re.search(r"(公司|企业|集团)[：:]\s*(\S+)", text)
    if m:
        return m.group(2)[:40]
    m = re.search(r"([一-龥A-Za-z0-9]{2,20}?(?:科技|网络|信息|集团|有限公司|公司))", text)
    return m.group(1) if m else ""


def _split_resp_req(text: str) -> tuple[list[str], list[str]]:
    """按职责/要求标题把正文分成两段，返回要点列表。"""
    lines = text.splitlines()
    bucket: str | None = None
    resp: list[str] = []
    req: list[str] = []
    for line in lines:
        s = line.strip()
        low = s.lower()
        if any(h in low for h in _RESP_HEADERS) and len(s) <= 20:
            bucket = "resp"
            continue
        if any(h in low for h in _REQ_HEADERS) and len(s) <= 20:
            bucket = "req"
            continue
        if not s:
            continue
        point = s.lstrip(" -•·●0123456789.、)")
        if not point:
            continue
        if bucket == "resp":
            resp.append(point)
        elif bucket == "req":
            req.append(point)
    return resp[:12], req[:12]


def _classify_lines(text: str) -> tuple[list[str], list[str]]:
    """把每一行归入“必备上下文”或“加分上下文”。

    默认归为必备；仅当该行含加分线索且不含必备线索时归为加分。
    """
    must_lines: list[str] = []
    nice_lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        has_nice = any(re.search(c, s) for c in _NICE_CUES)
        has_must = any(c in s for c in _MUST_CUES)
        if has_nice and not has_must:
            nice_lines.append(s)
        else:
            must_lines.append(s)
    return must_lines, nice_lines


def _collect_terms(lines: list[str]) -> list[str]:
    """从若干行里收集命中的技能原始词。"""
    terms: list[str] = []
    joined = "\n".join(lines)
    for _key, hit_terms in skills.match_skills(joined).items():
        terms.extend(hit_terms)
    return terms


def _extract_requirements(text: str) -> list[str]:
    reqs: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _DEGREE_RE.search(s) or _GRADE_RE.search(s) or _INTERN_RE.search(s):
            point = s.lstrip(" -•·●0123456789.、)")
            if 2 <= len(point) <= 60:
                reqs.append(point)
    # 去重并限量
    return list(dict.fromkeys(reqs))[:8]


# ---------------------------------------------------------------------------
# 技能归一化
# ---------------------------------------------------------------------------


def _normalize(terms: list | None, raw_text: str, default_all: bool) -> list[dict]:
    """把候选技能词归一化为技能列表。

    LLM 抽取到的候选词用 normalize_terms 处理：能匹配本体的归一到规范节点，
    匹配不到的新兴技能（如 LangChain、向量数据库等）保留为 free-form，不被丢弃。
    候选为空且 default_all 时，回退为对全文做本体匹配（保证必备技能不至于全空）。
    """
    result = skills.normalize_terms([str(t) for t in (terms or [])])
    if not result and default_all:
        result = [
            {
                "key": key,
                "name": skills.skill_name(key),
                "category": skills.skill_category(key),
                "evidence": skills.dedup_evidence(evidence),
            }
            for key, evidence in skills.match_skills(raw_text).items()
        ]
        result.sort(key=lambda x: x["name"])
    return result
