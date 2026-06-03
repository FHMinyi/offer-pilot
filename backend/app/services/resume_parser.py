"""简历解析（PRD §7.1）。

把非结构化简历转成结构化数据。优先用 LLM，未配置时降级为规则解析。
规则模式重点保证“技能集合”的可靠抽取（缺口分析强依赖它），
段落/项目抽取尽力而为。
"""

from __future__ import annotations

import re

from . import llm, skills

# 常见简历分节标题关键词 -> 规范字段
_SECTION_HEADERS = {
    "education": ["教育背景", "教育经历", "学历", "education"],
    "internship": ["实习经历", "工作经历", "实习经验", "工作经验", "experience", "internship"],
    "projects": ["项目经历", "项目经验", "项目", "project"],
    "skills": ["专业技能", "技能", "技术栈", "skills", "技能清单"],
    "awards": ["获奖", "荣誉", "奖项", "证书", "award"],
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(1\d{10})(?!\d)")


def parse_resume(raw_text: str) -> dict:
    """解析简历，返回结构化 dict。"""
    try:
        data = _parse_with_llm(raw_text)
    except llm.LLMUnavailable:
        data = _parse_with_rules(raw_text)
    # 无论哪种模式，技能都用本体重新归一化一次，保证后续缺口分析口径一致
    data["skills"] = _normalize_skill_list(raw_text, data.get("skills"))
    return data


# ---------------------------------------------------------------------------
# LLM 模式
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """你是简历结构化解析器。请把简历文本解析为 JSON，字段如下：
- basic_info: {name, contact}
- education: 字符串数组，每项一段教育经历
- experiences: 数组，每项 {title, description}（实习/工作经历）
- projects: 数组，每项 {title, description, tech}（tech 为技术栈字符串数组）
- skills: 字符串数组（候选技能词，原文写法即可）
只输出 JSON，不要额外解释。"""


def _parse_with_llm(raw_text: str) -> dict:
    # 解析简历用 resume 角色模型（可配置为更快的小模型）
    data = llm.complete_json(_LLM_SYSTEM, raw_text, model=llm.model_for("resume"))
    # 容错：补齐缺失字段
    data.setdefault("basic_info", {})
    data.setdefault("education", [])
    data.setdefault("experiences", [])
    data.setdefault("projects", [])
    data.setdefault("skills", [])
    return data


# ---------------------------------------------------------------------------
# 规则模式
# ---------------------------------------------------------------------------


def _parse_with_rules(raw_text: str) -> dict:
    sections = _split_sections(raw_text)

    basic = _extract_basic_info(raw_text)
    education = _to_lines(sections.get("education", ""))
    experiences = _blocks_to_items(sections.get("internship", ""))
    projects = _blocks_to_items(sections.get("projects", ""), with_tech=True)

    return {
        "basic_info": basic,
        "education": education,
        "experiences": experiences,
        "projects": projects,
        "skills": [],  # 交由 parse_resume 统一归一化
    }


def _split_sections(text: str) -> dict[str, str]:
    """按行扫描，识别分节标题，把正文归入对应字段。"""
    lines = text.splitlines()
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        header = _match_header(stripped)
        if header:
            current = header
            result.setdefault(current, [])
            continue
        if current and stripped:
            result[current].append(stripped)
    return {k: "\n".join(v) for k, v in result.items()}


def _match_header(line: str) -> str | None:
    """判断某行是否为分节标题（标题一般较短）。"""
    if not line or len(line) > 18:
        return None
    low = line.lower()
    # 去掉可能的装饰符号
    cleaned = re.sub(r"[\s:：|\-—_#●•·]+", "", low)
    for field, keywords in _SECTION_HEADERS.items():
        for kw in keywords:
            if cleaned == kw or low.strip() == kw:
                return field
    return None


def _extract_basic_info(text: str) -> dict:
    head = "\n".join(text.splitlines()[:6])
    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    # 姓名启发式：首个较短的非空行
    name = ""
    for line in text.splitlines():
        s = line.strip()
        if 2 <= len(s) <= 8 and not _match_header(s) and "@" not in s:
            name = s
            break
    contact = " ".join(filter(None, [email.group(0) if email else "", phone.group(0) if phone else ""]))
    return {"name": name, "contact": contact.strip(), "_head": head}


def _to_lines(block: str) -> list[str]:
    return [ln.strip() for ln in block.splitlines() if ln.strip()]


def _blocks_to_items(block: str, with_tech: bool = False) -> list[dict]:
    """把一段文本按空行 / 项目符号切成若干条目。"""
    if not block.strip():
        return []
    # 优先按空行分块；若没有空行，则把每个以符号/数字开头的行视作新条目
    raw_blocks = re.split(r"\n\s*\n", block)
    if len(raw_blocks) == 1:
        raw_blocks = _split_by_bullets(block)

    items: list[dict] = []
    for rb in raw_blocks:
        lines = [ln.strip(" -•·●\t") for ln in rb.splitlines() if ln.strip()]
        if not lines:
            continue
        title = lines[0][:60]
        description = "\n".join(lines[1:]) if len(lines) > 1 else ""
        item = {"title": title, "description": description}
        if with_tech:
            tech_keys = skills.match_skills(rb)
            item["tech"] = [skills.skill_name(k) for k in tech_keys]
        items.append(item)
    return items


def _split_by_bullets(block: str) -> list[str]:
    blocks: list[str] = []
    buf: list[str] = []
    for line in block.splitlines():
        if re.match(r"^\s*([-•·●]|\d+[.、)])", line) and buf:
            blocks.append("\n".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    return blocks


# ---------------------------------------------------------------------------
# 技能归一化（两种模式共用）
# ---------------------------------------------------------------------------


def _normalize_skill_list(raw_text: str, llm_skills: list | None) -> list[dict]:
    """把全文 + LLM 给出的候选技能词统一归一化。

    返回 [{key, name, category, evidence:[原始词...]}]。
    - 全文做本体匹配，得到规则证据；
    - LLM 候选词用 normalize_terms：本体内归一、本体外（新兴技能如 LangChain）保留为 free-form，
      不被固定本体过滤，从而简历里的新兴技能也能被识别为「已具备」。
    evidence 即“简历里哪段经历/哪个词支持了该技能”（呼应 PRD §6.2）。
    """
    result: dict[str, dict] = {}

    # 1) 全文本体匹配（规则证据）
    for key, evidence in skills.match_skills(raw_text).items():
        result[key] = {
            "key": key,
            "name": skills.skill_name(key),
            "category": skills.skill_category(key),
            "evidence": list(evidence),
        }

    # 2) 合并 LLM 候选词（含 free-form 新兴技能）
    for s in skills.normalize_terms([str(x) for x in (llm_skills or [])]):
        if s["key"] in result:
            result[s["key"]]["evidence"].extend(s["evidence"])
        else:
            result[s["key"]] = dict(s)

    out = list(result.values())
    for s in out:
        s["evidence"] = skills.dedup_evidence(s["evidence"])
    out.sort(key=lambda x: x["name"])
    return out
