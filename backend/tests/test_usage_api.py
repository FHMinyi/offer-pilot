"""Token 用量端点契约测试：空库 200、record_usage 落库后 summary/timeseries 正确。

不依赖真实 LLM：直接用 record_usage（独立短 session）写入 TokenUsage，再打端点验证。
"""

from __future__ import annotations

from app.services.usage import (
    NormalizedUsage,
    record_usage,
    usage_context,
)


def test_summary_empty_db_returns_200_all_zero(client):
    # 用一个不会有任何记录的设备隔离查询
    r = client.get("/api/usage/summary", headers={"X-Device-Id": "empty-dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_input_hit"] == 0
    assert body["total_input_miss"] == 0
    assert body["total_output"] == 0
    assert body["total_calls"] == 0
    assert body["by_model"] == []
    assert body["by_path"] == []
    # 契约：不返回 hit_rate
    assert "hit_rate" not in body


def test_timeseries_empty_db_returns_200_with_skeleton(client):
    r = client.get(
        "/api/usage/timeseries",
        params={"granularity": "day", "group_by": "none", "tz_offset": 0},
        headers={"X-Device-Id": "empty-dev"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["granularity"] == "day"
    assert body["group_by"] == "none"
    assert len(body["bucket_starts"]) == 24
    # group_by=none 仍返回 1 条 series（key=all）
    assert len(body["series"]) == 1
    assert body["series"][0]["key"] == "all"
    assert body["series"][0]["label"] == "全部"
    assert len(body["series"][0]["buckets"]) == 24
    # 桶不含 total / hit_rate
    b0 = body["series"][0]["buckets"][0]
    assert set(b0.keys()) == {"bucket_start", "input_hit", "input_miss", "output"}


def test_record_then_summary_and_filter(client):
    dev = "usage-api-dev"
    with usage_context(user_id=dev, path="chat"):
        from app.services.usage import current_ctx

        record_usage(
            provider="openai",
            model="gpt-4o-mini",
            streamed=True,
            usage=NormalizedUsage(input_hit=100, input_miss=300, output=50),
            ctx=current_ctx(),
        )
    with usage_context(user_id=dev, path="resume"):
        from app.services.usage import current_ctx

        record_usage(
            provider="anthropic",
            model="claude-sonnet-4-6",
            streamed=False,
            usage=NormalizedUsage(input_hit=0, input_miss=200, output=80),
            ctx=current_ctx(),
        )

    r = client.get("/api/usage/summary", headers={"X-Device-Id": dev})
    assert r.status_code == 200
    body = r.json()
    assert body["total_input_hit"] == 100
    assert body["total_input_miss"] == 500
    assert body["total_output"] == 130
    assert body["total_calls"] == 2
    # by_path 含 chat / resume，且按 input_miss 降序（resume 200 排在 chat 300 之后）
    paths = [g["key"] for g in body["by_path"]]
    assert set(paths) == {"chat", "resume"}
    assert body["by_path"][0]["input_miss"] >= body["by_path"][1]["input_miss"]
    # by_path 的 provider 为空
    assert all(g["provider"] == "" for g in body["by_path"])
    # by_model provider 非空
    model_map = {g["key"]: g for g in body["by_model"]}
    assert model_map["gpt-4o-mini"]["provider"] == "openai"

    # path 过滤
    r2 = client.get("/api/usage/summary", params={"path": "chat"}, headers={"X-Device-Id": dev})
    b2 = r2.json()
    assert b2["total_calls"] == 1
    assert b2["total_input_miss"] == 300


def test_record_zero_total_is_not_persisted(client):
    dev = "usage-zero-dev"
    with usage_context(user_id=dev, path="chat"):
        from app.services.usage import current_ctx

        record_usage(
            provider="openai",
            model="gpt-4o-mini",
            streamed=False,
            usage=NormalizedUsage(),  # total == 0
            ctx=current_ctx(),
        )
    r = client.get("/api/usage/summary", headers={"X-Device-Id": dev})
    assert r.json()["total_calls"] == 0


def test_device_isolation(client):
    """统计强制按设备过滤：A 设备的记录不应出现在 B 设备的汇总里。"""
    with usage_context(user_id="dev-A", path="chat"):
        from app.services.usage import current_ctx

        record_usage(
            provider="openai",
            model="m",
            streamed=False,
            usage=NormalizedUsage(input_miss=10, output=5),
            ctx=current_ctx(),
        )
    r = client.get("/api/usage/summary", headers={"X-Device-Id": "dev-B"})
    assert r.json()["total_calls"] == 0
