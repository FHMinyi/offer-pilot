"""Token 用量统计子系统中枢：归一、上下文、落库、分桶。

全链路统一命名 input_hit / input_miss / output（DB 列=API=SSE=前端类型，绝不出现
cached/uncached）。两家语义相反：OpenAI 的 prompt_tokens 含 cached（miss=prompt-cached）；
Anthropic 的 input_tokens 不含缓存读写（miss=input+cache_creation）。

设计要点：
- normalize_usage 把各 provider 原始 usage 归一为 NormalizedUsage（None/缺字段→0）。
- contextvars 承载本次调用的归属（path/user_id/conversation_id/analysis_run_id），
  与 llm.py 的 use_llm_override / set_override 同构，供 record_usage 落库时取用。
- record_usage 用【独立短 session】落库，绝不复用请求 session（避免与业务事务纠缠、
  在流式/线程池场景下踩 session 生命周期）。
- 分桶在 Python 应用层做（不用 SQLite strftime）：created_at(UTC)+tz_offset 偏移后取
  本地 .hour/.date() 落桶；day=24 整点小时 / week=7 日 / month=30 日，连续补零。
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..database import SessionLocal
from ..models import TokenUsage

logger = logging.getLogger("offerpilot.usage")


@dataclass(frozen=True)
class NormalizedUsage:
    """归一后的三类 token（与全链路命名一致）。"""

    input_hit: int = 0
    input_miss: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.input_hit + self.input_miss + self.output


def _as_int(v) -> int:
    """None/缺失/非数 → 0；否则取整。"""
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _get(usage, *names):
    """从 SDK pydantic 对象或 dict 按多候选名取首个非 None 值；都没有则 None。"""
    if usage is None:
        return None
    for name in names:
        if isinstance(usage, dict):
            val = usage.get(name)
        else:
            val = getattr(usage, name, None)
        if val is not None:
            return val
    return None


def normalize_usage(provider: str, raw_usage) -> NormalizedUsage:
    """把各 provider 的原始 usage 归一为 NormalizedUsage。raw_usage 为 None → 全 0。

    映射（契约）：
    - input_hit：OpenAI prompt_tokens_details.cached_tokens；DeepSeek prompt_cache_hit_tokens；
      Anthropic cache_read_input_tokens
    - input_miss：OpenAI (prompt_tokens - cached)；DeepSeek prompt_cache_miss_tokens；
      Anthropic (input_tokens + cache_creation_input_tokens)
    - output：OpenAI/DeepSeek completion_tokens；Anthropic output_tokens
    """
    if raw_usage is None:
        return NormalizedUsage()

    provider = (provider or "").lower()

    if provider == "openai":
        prompt = _as_int(_get(raw_usage, "prompt_tokens"))
        output = _as_int(_get(raw_usage, "completion_tokens"))
        # 先看 DeepSeek 顶层缓存字段（语义同 OpenAI：prompt 含 cached）
        ds_hit = _get(raw_usage, "prompt_cache_hit_tokens")
        ds_miss = _get(raw_usage, "prompt_cache_miss_tokens")
        if ds_hit is not None or ds_miss is not None:
            hit = _as_int(ds_hit)
            miss = _as_int(ds_miss) if ds_miss is not None else max(0, prompt - hit)
            return NormalizedUsage(input_hit=hit, input_miss=miss, output=output)
        # 标准 OpenAI：cached 在 prompt_tokens_details.cached_tokens
        details = _get(raw_usage, "prompt_tokens_details")
        cached = _as_int(_get(details, "cached_tokens")) if details is not None else 0
        hit = min(cached, prompt)
        miss = max(0, prompt - hit)
        return NormalizedUsage(input_hit=hit, input_miss=miss, output=output)

    if provider == "anthropic":
        hit = _as_int(_get(raw_usage, "cache_read_input_tokens"))
        miss = _as_int(_get(raw_usage, "input_tokens")) + _as_int(
            _get(raw_usage, "cache_creation_input_tokens")
        )
        output = _as_int(_get(raw_usage, "output_tokens"))
        return NormalizedUsage(input_hit=hit, input_miss=miss, output=output)

    return NormalizedUsage()


# ---------------------------------------------------------------------------
# 归属上下文（contextvars）：与 llm.py 的 use_llm_override / set_override 同构。
# 外层先设 user_id（如路由层），内层只补 path（如 pipeline），互不覆盖。
# ---------------------------------------------------------------------------
_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("usage_ctx", default={})


@contextmanager
def usage_context(
    *,
    path: str | None = None,
    user_id: str | None = None,
    conversation_id: int | None = None,
    analysis_run_id: int | None = None,
):
    """把非 None 项合并进当前归属上下文，with 块内生效、退出自动重置。

    不覆盖已存在的非空键：便于外层先设 user_id、内层只补 path（外层值优先保留）。
    注意 contextvars 不传播到子线程，并发需用 copy_context().run 携带（见 pipeline.py）。
    """
    incoming = {
        "path": path,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "analysis_run_id": analysis_run_id,
    }
    current = _ctx.get() or {}
    merged = dict(current)
    for k, v in incoming.items():
        if v is None:
            continue
        # 不覆盖已存在的非空键
        if merged.get(k):
            continue
        merged[k] = v
    token = _ctx.set(merged)
    try:
        yield
    finally:
        _ctx.reset(token)


def set_usage_context(d: dict) -> None:
    """在【当前】context 内设置归属（不返回 token、不负责重置）。

    供流式路由用 ``copy_context().run(set_usage_context, ...)`` 在专属 context 里设一次，
    再用同一 context 驱动整个 SSE 生成器（仿 llm.set_override，见 routers/chat.py）。
    """
    current = _ctx.get() or {}
    merged = dict(current)
    for k, v in (d or {}).items():
        if v is None:
            continue
        merged[k] = v
    _ctx.set(merged)


def current_ctx() -> dict:
    """返回当前归属上下文（空时返回空 dict）。"""
    return _ctx.get() or {}


# ---------------------------------------------------------------------------
# 本轮累加（contextvars）：对话一轮内多步 LLM 调用的 token 汇总，供 SSE usage 事件。
# ---------------------------------------------------------------------------
_turn_acc: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "usage_turn_acc", default=None
)


@contextmanager
def turn_accumulator():
    """开一个本轮累加器：with 块内 record_usage 会把四项累加进去。

    yield 一个 getter，返回累加 dict（含 input_hit/input_miss/output/total）。
    """
    acc = {"input_hit": 0, "input_miss": 0, "output": 0, "total": 0}
    token = _turn_acc.set(acc)
    try:
        yield lambda: acc
    finally:
        _turn_acc.reset(token)


def record_usage(*, provider: str, model: str, streamed: bool, usage: NormalizedUsage, ctx: dict):
    """把一次调用的用量累加进本轮累加器（若有）并落库（独立短 session）。

    provider 不在 {openai,anthropic} 或 usage.total==0 直接 return（不记空账）。
    """
    if provider not in ("openai", "anthropic") or usage.total == 0:
        return

    acc = _turn_acc.get()
    if acc is not None:
        acc["input_hit"] += usage.input_hit
        acc["input_miss"] += usage.input_miss
        acc["output"] += usage.output
        acc["total"] += usage.total

    ctx = ctx or {}
    db = SessionLocal()
    try:
        row = TokenUsage(
            user_id=ctx.get("user_id") or "local",
            conversation_id=ctx.get("conversation_id"),
            analysis_run_id=ctx.get("analysis_run_id"),
            provider=provider,
            model=model or "",
            path=ctx.get("path") or "unknown",
            streamed=streamed,
            input_hit=usage.input_hit,
            input_miss=usage.input_miss,
            output=usage.output,
            total=usage.total,
        )
        db.add(row)
        db.commit()
    except Exception as exc:  # noqa: BLE001 统计落库失败绝不连累业务，仅告警
        logger.warning("record_usage 落库失败：%s", exc)
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 分桶工具：在应用层按本地时间落桶（不用 SQLite strftime），供 routers/usage.py 调用。
# ---------------------------------------------------------------------------


def _to_aware_utc(dt: datetime) -> datetime:
    """SQLite 取回的 created_at 可能是 naive（UTC 墙钟）；补上 UTC 时区。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bucket_axis(
    rows, granularity: str, tz_offset: int, now_utc: datetime
) -> list[datetime]:
    """生成连续桶起点（UTC 时刻，代表本地桶边界），以 now 收尾；空 rows 也返回完整骨架。

    - day：过去 24h 按本地整点小时（24 桶）
    - week：过去 7 天按本地日（7 桶）
    - month：过去 30 天按本地日（30 桶）
    返回的每个元素是该本地桶起点对应的 UTC datetime（aware）。
    """
    offset = timedelta(minutes=tz_offset)
    local_now = _to_aware_utc(now_utc) + offset

    if granularity == "day":
        # 本地当前整点小时为最后一个桶
        local_end = local_now.replace(minute=0, second=0, microsecond=0)
        starts_local = [local_end - timedelta(hours=23 - i) for i in range(24)]
    elif granularity == "week":
        local_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        starts_local = [local_today - timedelta(days=6 - i) for i in range(7)]
    else:  # month
        local_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        starts_local = [local_today - timedelta(days=29 - i) for i in range(30)]

    # 本地桶起点 → 还原为 UTC 时刻（减回偏移），统一带 UTC 时区输出
    return [(s - offset).replace(tzinfo=timezone.utc) for s in starts_local]


def _bucketize(
    rows, bucket_starts: list[datetime], granularity: str, tz_offset: int
) -> list[dict]:
    """把每行落到对应桶累加三类 token；缺桶补零；返回与 bucket_starts 等长、逐桶对齐的列表。

    每个元素：{"input_hit":int, "input_miss":int, "output":int}。
    """
    offset = timedelta(minutes=tz_offset)
    out = [{"input_hit": 0, "input_miss": 0, "output": 0} for _ in bucket_starts]

    if not bucket_starts:
        return out

    # 把桶起点也转成「本地键」，便于用行的本地键直接索引
    if granularity == "day":
        # 键：(本地日期, 本地小时)
        index = {}
        for i, b in enumerate(bucket_starts):
            local_b = _to_aware_utc(b) + offset
            index[(local_b.date(), local_b.hour)] = i
        for r in rows:
            local = _to_aware_utc(r.created_at) + offset
            i = index.get((local.date(), local.hour))
            if i is None:
                continue
            out[i]["input_hit"] += int(r.input_hit or 0)
            out[i]["input_miss"] += int(r.input_miss or 0)
            out[i]["output"] += int(r.output or 0)
    else:
        # week / month 键：本地日期
        index = {}
        for i, b in enumerate(bucket_starts):
            local_b = _to_aware_utc(b) + offset
            index[local_b.date()] = i
        for r in rows:
            local = _to_aware_utc(r.created_at) + offset
            i = index.get(local.date())
            if i is None:
                continue
            out[i]["input_hit"] += int(r.input_hit or 0)
            out[i]["input_miss"] += int(r.input_miss or 0)
            out[i]["output"] += int(r.output or 0)

    return out
