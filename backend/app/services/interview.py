"""面经复盘 → 盲区提取 → 权重回灌（轨道 F1 · 碰壁期闭环）。

一个漂亮的技术闭环：把「面试受挫」转化为「下一轮学习的优先级」。
- **盲区提取** `extract_blind_spots`：LLM 优先（`complete_json`，结构化抽被问倒/不熟的技能 +
  严重度），未配置或失败时降级规则（`match_skills` 在面经文本里匹配技能本体）。两路都把技能
  归一到技能本体节点（命中不到的新兴技能保留为 freeform）；并与本次分析已知缺口交叉，
  命中缺口的盲区升级为 high（面试印证了简历分析里就标出的缺口）。
- **权重回灌** `reweight_from_blind_spots`：命中盲区的未完成 Task → `weight` 按严重度提升
  （capped 10）+ `planned_date` 拉到今天，立即进入「今日任务」。计划未覆盖的盲区由调用方
  作「建议加练」展示（MVP 不自动建任务）。

`Task.skill_key` 存的是 roadmap 的 focus 名（非规范 key），故任务匹配按
`match_skills(title + skill_key)` 归一后再比对，提高召回。
"""

from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy import select

from ..models import AnalysisRun, JourneyState, Task
from .llm import LLMUnavailable, complete_json
from .skills import match_skills, skill_name

logger = logging.getLogger("offerpilot.interview")

# 严重度 → 权重增量；上限对齐 schemas.TaskPatchRequest.weight 的 0..10。
# 下限取 +2：保证回灌后 weight≥3，被「每日结算」降权一次（-1）后仍 ≥2，重点高亮不会一结算就闪退。
_SEVERITY_BOOST = {"high": 4, "mid": 3, "low": 2}
_WEIGHT_MAX = 10
_MAX_SPOTS = 12

# 模型常用的同义严重度 → 规范三档（high/mid/low）
_SEVERITY_ALIASES = {
    "high": "high", "critical": "high", "severe": "high", "严重": "high",
    "medium": "mid", "mid": "mid", "moderate": "mid", "一般": "mid", "中": "mid",
    "low": "low", "minor": "low", "轻微": "low", "低": "low",
}


def _norm_severity(raw: object) -> str:
    """把模型返回的各种严重度写法规整到 high/mid/low（无法识别按 mid）。"""
    return _SEVERITY_ALIASES.get(str(raw or "").strip().lower(), "mid")


def _freeform_key(term: str) -> str:
    """未收录技能的稳定 key：小写 + 压缩空白（与 skills._freeform_key 同口径）。"""
    return re.sub(r"\s+", " ", term.strip().lower())


def _gap_keys(run: AnalysisRun | None) -> set[str]:
    """本次分析里已识别的技能缺口 key 集合（用于给面试盲区升级严重度）。"""
    if run is None:
        return set()
    sg = (run.result or {}).get("skill_gap") or {}
    keys: set[str] = set()
    for grp in ("must_have_gaps", "nice_to_have_gaps"):
        for g in sg.get(grp) or []:
            k = g.get("key")
            if k:
                keys.add(str(k))
    return keys


def _extract_rule(content: str) -> list[dict]:
    """规则降级：面经文本里匹配到的技能本体节点即视为盲区候选（severity 默认 mid）。"""
    spots: list[dict] = []
    for key, evid in match_skills(content).items():
        spots.append(
            {
                "skill_key": key,
                "skill_name": skill_name(key),
                "severity": "mid",
                "evidence": evid,
                "matched": False,
            }
        )
    spots.sort(key=lambda s: s["skill_name"])
    return spots


def _extract_llm(content: str) -> list[dict]:
    """LLM 抽取被问倒/不熟的技能 + 严重度，再归一到技能本体。失败抛 LLMUnavailable。"""
    system = (
        "你是资深技术面试官助理。用户会贴一段面试复盘/面经，请提取其中暴露出的【技能盲区】"
        "——被问倒、答不上、或明显不熟的技能点。只输出一个 JSON 对象："
        '{"blind_spots":[{"skill":"技能名(尽量用通用规范名,如 TypeScript/React/算法/HTTP)",'
        '"severity":"high|mid|low","evidence":"被问到的点(简短)"}]}。'
        "severity：完全答不上=high，答得磕绊/不深入=mid，只是不够熟练=low。"
        f"最多 {_MAX_SPOTS} 条，按严重度从高到低。"
    )
    data = complete_json(system, f"面试复盘：\n{content}")
    raw = data.get("blind_spots") or []
    spots: list[dict] = []
    seen: set[str] = set()
    for item in raw:
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
    return spots[:_MAX_SPOTS]


def extract_blind_spots(content: str, run: AnalysisRun | None = None) -> list[dict]:
    """从面经文本提取盲区（LLM 优先，规则降级）；命中已知缺口的盲区升级为 high。"""
    content = (content or "").strip()
    if not content:
        return []
    try:
        spots = _extract_llm(content)
    except LLMUnavailable:
        spots = _extract_rule(content)
    except Exception:  # noqa: BLE001 LLM 路径任何意外都降级规则，绝不打穿到 500
        logger.exception("LLM 盲区抽取异常，降级为规则匹配")
        spots = _extract_rule(content)
    # 与本次分析已识别的缺口交叉：面试印证的缺口升级为 high
    gaps = _gap_keys(run)
    if gaps:
        for s in spots:
            if s["skill_key"] in gaps:
                s["severity"] = "high"
    return spots


def reweight_from_blind_spots(
    db,
    journey: JourneyState,
    blind_spots: list[dict],
    *,
    today: date | None = None,
) -> dict:
    """命中盲区的未完成 Task → 提 weight(capped) + planned_date 拉到今天。

    只 `flush` 不 `commit`：把事务边界交给调用方（路由），让「回灌 + matched 回填」
    成为一个原子事务——任一步失败可整体回滚，避免「任务已改但响应说没改」的不一致。
    返回 {boosted: list[Task], matched_keys: set[str]}。
    """
    if today is None:
        today = date.today()
    run_id = journey.analysis_run_id
    if run_id is None or not blind_spots:
        return {"boosted": [], "matched_keys": set()}

    # 盲区 key → 权重增量（同 key 多条取最重）
    spot_boost: dict[str, int] = {}
    for s in blind_spots:
        k = s.get("skill_key")
        if not k:
            continue
        b = _SEVERITY_BOOST.get(s.get("severity", "mid"), 2)
        spot_boost[k] = max(spot_boost.get(k, 0), b)
    spot_keys = set(spot_boost)

    tasks = db.scalars(
        select(Task)
        .where(Task.analysis_run_id == run_id, Task.status.in_(("todo", "doing")))
        .order_by(Task.week.asc(), Task.order_index.asc())
    ).all()

    boosted: list[Task] = []
    matched_keys: set[str] = set()
    for t in tasks:
        t_keys = set(match_skills(f"{t.title} {t.skill_key or ''}"))
        hit = t_keys & spot_keys
        if not hit:
            continue
        boost = max(spot_boost[k] for k in hit)
        t.weight = min(_WEIGHT_MAX, (t.weight or 0) + boost)
        t.planned_date = today  # 拉到今天，立即进入「今日任务」
        boosted.append(t)
        matched_keys |= hit

    db.flush()  # 落到事务但不提交，提交由路由统一负责（见 docstring）
    return {"boosted": boosted, "matched_keys": matched_keys}
