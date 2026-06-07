"""费曼/出题判定学习掌握度（学习闭环引擎的第二个实例 · 把校验前移到学习环节）。

与 F1 面经复盘同构、共用同一套引擎：
  用户复述 / 出题作答 → AI 判定(verdict + gaps) → gaps 经 `gaps_to_blind_spots` 归一为
  与 InterviewLog.blind_spots 完全同构的结构 → 复用 `interview.reweight_from_blind_spots`
  回灌到匹配 Task（提 weight + 拉到今天）。

判定强依赖 LLM 的语义判断，规则无法真正「判定是否掌握」。故未配置 / 调用失败时
**不返回假判定**，而是返回 available=False 的降级信号（feedback 引导用户走「我已掌握」
手动标记）。这呼应产品决策：AI 当教练不当法官，误判 / 缺席都不卡死用户。

归一逻辑（技能名→技能本体 / freeform）直接复用 interview 模块的私有 helper，
零重复、零改动 F1。
"""

from __future__ import annotations

import logging

from ..models import Task
from .interview import _freeform_key, _norm_severity
from .llm import LLMUnavailable, complete_json, engine_name
from .skills import match_skills, skill_name

logger = logging.getLogger("offerpilot.mastery")

_VERDICT_VALUES = {"excellent", "good", "fair", "poor"}
_MAX_FOLLOWUPS = 3
_MAX_QUESTIONS = 3

# 降级（无 LLM / 失败）时的统一信号：不评级、引导手动标记。
_UNAVAILABLE_FEEDBACK = "当前未配置 AI 判定能力。你可以自行确认是否已掌握后，点「我已掌握 ⭐」手动标记。"

# 「教练不当法官」判定骨架（费曼与判分共用）：先肯定，再点缺口，鼓励语气。
_COACH_INTRO = (
    "你是一位严谨又友善的学习教练，正在检验用户对某个技能点的真实掌握程度。"
    "你是教练不是法官：先肯定讲得好/答得对的地方，再点出模糊、错误或缺失之处；"
    "即使判定不通过，语气也要鼓励，让用户清楚差在哪、怎么补，而不是单纯否定。"
)

# 判定输出的 JSON 契约（字面量，勿用 .format 以免与 {} 冲突）。
_JUDGE_JSON_SPEC = (
    "只输出一个 JSON 对象：\n"
    '{"verdict":"excellent|good|fair|poor",'
    '"feedback":"2-4 句建设性反馈(中文)：先肯定再指出缺口",'
    '"gaps":[{"skill":"暴露出的薄弱子点(尽量用通用规范名,如 TypeScript/React/HTTP/算法)",'
    '"severity":"high|mid|low","evidence":"没讲清/答错的具体点(简短)"}],'
    '"followup_questions":["1-2 个能暴露理解深度的追问(中文)"]}\n'
    "verdict：透彻准确=excellent，基本讲清=good，有明显漏洞=fair，没讲到点上=poor。"
    "severity：完全没理解=high，理解但讲不深=mid，只是细节遗漏=low。gaps 没有就空数组。"
)


def _skill_label(task: Task) -> str:
    """判定 prompt 里展示的技能方向：优先 skill_key，缺失回退任务标题。"""
    return (task.skill_key or "").strip() or task.title


def _norm_verdict(raw: object) -> str:
    """模型返回的 verdict 规整到四档（无法识别按 fair，给中性偏保守评级）。"""
    v = str(raw or "").strip().lower()
    return v if v in _VERDICT_VALUES else "fair"


def gaps_to_blind_spots(gaps: list[dict] | None) -> list[dict]:
    """把判定 gaps([{skill,severity,evidence}]) 归一为 reweight_from_blind_spots 可直接消费的
    blind_spots 同构结构（与 interview._extract_llm 同口径：本体命中归一、未收录保留 freeform）。"""
    spots: list[dict] = []
    seen: set[str] = set()
    for item in gaps or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("skill") or "").strip()
        if not name:
            continue
        sev = _norm_severity(item.get("severity"))
        ev = item.get("evidence")
        ev_list = [str(ev)] if ev else [name]
        matched = match_skills(name)
        if matched:
            for key in matched:
                if key in seen:
                    continue
                seen.add(key)
                spots.append(
                    {
                        "skill_key": key,
                        "skill_name": skill_name(key),
                        "severity": sev,
                        "evidence": ev_list,
                        "matched": False,
                    }
                )
        else:
            key = _freeform_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            spots.append(
                {
                    "skill_key": key,
                    "skill_name": name,
                    "severity": sev,
                    "evidence": ev_list,
                    "matched": False,
                }
            )
    return spots


def _degraded() -> dict:
    """LLM 不可用 / 失败时的判定降级信号（不返回假判定）。"""
    return {
        "verdict": "",
        "passed": False,
        "feedback": _UNAVAILABLE_FEEDBACK,
        "followup_questions": [],
        "gaps": [],
        "engine": "rule",
        "available": False,
    }


def _parse_judgement(data: dict) -> dict:
    """把模型返回的判定 JSON 解析为标准结果（verdict/passed/feedback/followups/gaps）。"""
    verdict = _norm_verdict(data.get("verdict"))
    feedback = str(data.get("feedback") or "").strip()
    raw_gaps = data.get("gaps")
    gaps = gaps_to_blind_spots(raw_gaps if isinstance(raw_gaps, list) else [])
    raw_fq = data.get("followup_questions")
    followups = (
        [str(q).strip() for q in raw_fq if str(q).strip()][:_MAX_FOLLOWUPS]
        if isinstance(raw_fq, list)
        else []
    )
    return {
        "verdict": verdict,
        "passed": verdict in ("excellent", "good"),  # fair/poor 不自动 mastered，用户仍可手动覆盖
        "feedback": feedback,
        "followup_questions": followups,
        "gaps": gaps,
        "engine": engine_name(),
        "available": True,
    }


def judge_feynman(content: str, task: Task) -> dict:
    """费曼复述判定。返回 {verdict, passed, feedback, followup_questions, gaps, engine, available}。"""
    content = (content or "").strip()
    if not content:
        return _degraded()
    system = (
        f"{_COACH_INTRO}\n"
        "用户会用自己的话讲解他刚学的内容（费曼学习法）。请先当一个完全不懂的「门外汉」"
        "判断他讲清楚了没有，再当「面试官」追问能暴露理解深度的问题。\n"
        f"学习任务：{task.title}（技能方向：{_skill_label(task)}）\n"
        f"{_JUDGE_JSON_SPEC}"
    )
    try:
        data = complete_json(system, f"用户的复述：\n{content}")
    except LLMUnavailable:
        return _degraded()
    except Exception:  # noqa: BLE001 LLM 路径任何意外都降级，绝不打穿到 500
        logger.exception("费曼判定 LLM 异常，降级")
        return _degraded()
    return _parse_judgement(data)


def generate_quiz(task: Task) -> dict:
    """出题（quiz 第一步）。返回 {questions:[{q,hint}], available}。"""
    system = (
        "你是出题教练。针对下面这个学习任务，出 2-3 道能检验真实掌握度的题"
        "（概念题 + 应用/场景题混合，避免纯记忆题）。只输出一个 JSON 对象："
        '{"questions":[{"q":"题目(中文)","hint":"可选的作答方向提示，没有就空串"}]}\n'
        f"学习任务：{task.title}（技能方向：{_skill_label(task)}）"
    )
    try:
        data = complete_json(system, "请出题。")
    except LLMUnavailable:
        return {"questions": [], "available": False}
    except Exception:  # noqa: BLE001
        logger.exception("出题 LLM 异常，降级")
        return {"questions": [], "available": False}
    raw = data.get("questions")
    questions: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or "").strip()
        if not q:
            continue
        questions.append({"q": q, "hint": str(item.get("hint") or "").strip()})
    questions = questions[:_MAX_QUESTIONS]
    if not questions:
        return {"questions": [], "available": False}
    return {"questions": questions, "available": True}


def judge_quiz(questions: list[dict] | None, answers: list[str] | None, task: Task) -> dict:
    """判分（quiz 第二步）。与 judge_feynman 在 verdict 之后完全合流（同一回灌/存档/回包）。"""
    answers = answers or []
    qa_lines: list[str] = []
    for i, q in enumerate(questions or []):
        prompt = str((q or {}).get("q") or "").strip() if isinstance(q, dict) else str(q).strip()
        ans = answers[i].strip() if i < len(answers) and answers[i] else "(未作答)"
        qa_lines.append(f"题目{i + 1}：{prompt}\n回答{i + 1}：{ans}")
    if not qa_lines:
        return _degraded()
    system = (
        f"{_COACH_INTRO}\n"
        "用户在做一组检验题，请你批改并据此判定其对该技能点的掌握程度。\n"
        f"学习任务：{task.title}（技能方向：{_skill_label(task)}）\n"
        f"{_JUDGE_JSON_SPEC}"
    )
    try:
        data = complete_json(system, "用户的答题：\n" + "\n\n".join(qa_lines))
    except LLMUnavailable:
        return _degraded()
    except Exception:  # noqa: BLE001
        logger.exception("判分 LLM 异常，降级")
        return _degraded()
    return _parse_judgement(data)
