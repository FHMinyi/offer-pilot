"""Token 用量子系统单测：normalize_usage 四种 usage shape + 分桶（跨午夜 / 空集补零）。

不依赖真实 LLM / 数据库；用普通对象或 dict 模拟 SDK usage 与 ORM 行。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.usage import _bucket_axis, _bucketize, normalize_usage


# ---------------------------------------------------------------------------
# normalize_usage：四种 shape
# ---------------------------------------------------------------------------


def test_normalize_none_is_all_zero():
    nu = normalize_usage("openai", None)
    assert (nu.input_hit, nu.input_miss, nu.output, nu.total) == (0, 0, 0, 0)


def test_normalize_openai_standard_with_cached_details():
    """标准 OpenAI：prompt_tokens 含 cached；miss = prompt - cached。"""
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=300),
    )
    nu = normalize_usage("openai", usage)
    assert nu.input_hit == 300
    assert nu.input_miss == 700  # 1000 - 300
    assert nu.output == 200
    assert nu.total == 1200


def test_normalize_deepseek_top_level_hit_miss():
    """DeepSeek 顶层 prompt_cache_hit_tokens / prompt_cache_miss_tokens（dict 模拟）。"""
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 150,
        "prompt_cache_hit_tokens": 600,
        "prompt_cache_miss_tokens": 400,
    }
    nu = normalize_usage("openai", usage)
    assert nu.input_hit == 600
    assert nu.input_miss == 400
    assert nu.output == 150
    assert nu.total == 1150


def test_normalize_deepseek_hit_only_derives_miss():
    """DeepSeek 只给 hit、没给 miss 时，miss 由 prompt - hit 兜底推导。"""
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 600,
    }
    nu = normalize_usage("openai", usage)
    assert nu.input_hit == 600
    assert nu.input_miss == 400  # max(0, 1000 - 600)
    assert nu.output == 0


def test_normalize_anthropic_cache_read_and_creation():
    """Anthropic：input_tokens 不含缓存读写；miss = input + cache_creation；hit = cache_read。"""
    usage = SimpleNamespace(
        input_tokens=500,
        output_tokens=120,
        cache_read_input_tokens=800,
        cache_creation_input_tokens=200,
    )
    nu = normalize_usage("anthropic", usage)
    assert nu.input_hit == 800
    assert nu.input_miss == 700  # 500 + 200
    assert nu.output == 120
    assert nu.total == 1620


def test_normalize_legacy_openai_no_cache_fields():
    """老模型无任何缓存字段：hit=0，miss=prompt 全量。"""
    usage = SimpleNamespace(prompt_tokens=400, completion_tokens=100)
    nu = normalize_usage("openai", usage)
    assert nu.input_hit == 0
    assert nu.input_miss == 400
    assert nu.output == 100


def test_normalize_unknown_provider_is_zero():
    usage = SimpleNamespace(prompt_tokens=400, completion_tokens=100)
    nu = normalize_usage("cohere", usage)
    assert nu.total == 0


# ---------------------------------------------------------------------------
# 分桶：_bucket_axis 骨架 / _bucketize 落桶 + 补零 + 跨午夜
# ---------------------------------------------------------------------------


class _Row:
    """模拟 TokenUsage 行（只需 created_at + 三类 token）。"""

    def __init__(self, created_at, input_hit=0, input_miss=0, output=0):
        self.created_at = created_at
        self.input_hit = input_hit
        self.input_miss = input_miss
        self.output = output


def test_bucket_axis_day_has_24_buckets_even_when_empty():
    now = datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc)
    axis = _bucket_axis([], "day", tz_offset=0, now_utc=now)
    assert len(axis) == 24
    # 连续整点小时、逐桶递增 1h
    for a, b in zip(axis, axis[1:]):
        assert b - a == timedelta(hours=1)


def test_bucket_axis_week_30day_skeletons():
    now = datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc)
    assert len(_bucket_axis([], "week", tz_offset=0, now_utc=now)) == 7
    assert len(_bucket_axis([], "month", tz_offset=0, now_utc=now)) == 30


def test_bucketize_empty_returns_full_zero_skeleton():
    now = datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc)
    axis = _bucket_axis([], "week", tz_offset=0, now_utc=now)
    out = _bucketize([], axis, "week", tz_offset=0)
    assert len(out) == 7
    assert all(b == {"input_hit": 0, "input_miss": 0, "output": 0} for b in out)


def test_bucketize_falls_into_correct_local_day_bucket():
    now = datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc)
    axis = _bucket_axis([], "week", tz_offset=0, now_utc=now)
    # 今天（UTC 6/10）一行
    row = _Row(datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc), input_hit=5, input_miss=3, output=2)
    out = _bucketize([row], axis, "week", tz_offset=0)
    # 最后一个桶 = 今天
    assert out[-1] == {"input_hit": 5, "input_miss": 3, "output": 2}
    assert sum(b["output"] for b in out) == 2


def test_bucketize_cross_midnight_with_tz_offset():
    """tz_offset 把 UTC 时刻推到「本地次日」，应落进对应本地日桶（验证不是按 UTC 日落桶）。"""
    # 东八区（+480 分钟）。UTC 6/9 23:00 -> 本地 6/10 07:00，应算「本地 6/10」。
    now_utc = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)  # 本地 6/10 20:00
    tz = 480
    axis = _bucket_axis([], "week", tz_offset=tz, now_utc=now_utc)
    row = _Row(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc), input_hit=1, input_miss=1, output=1)
    out = _bucketize([row], axis, "week", tz_offset=tz)
    # 本地 6/10 是最后一个桶；该行应落在最后一桶，而非倒数第二（若错按 UTC 日会落 6/9）
    assert out[-1] == {"input_hit": 1, "input_miss": 1, "output": 1}
    assert out[-2] == {"input_hit": 0, "input_miss": 0, "output": 0}


def test_bucketize_day_hour_granularity():
    now = datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc)
    axis = _bucket_axis([], "day", tz_offset=0, now_utc=now)  # 24 桶，末桶=15:00
    row = _Row(datetime(2026, 6, 10, 15, 5, tzinfo=timezone.utc), output=9)
    out = _bucketize([row], axis, "day", tz_offset=0)
    assert out[-1]["output"] == 9  # 落在 15:00 桶
    assert sum(b["output"] for b in out) == 9
