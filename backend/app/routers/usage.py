"""Token 用量统计路由：时间序列 + 汇总。

两端点都强制按设备过滤（user_id），不走 ownership 放行——统计只看本设备的账。
分桶在应用层做（services.usage 提供 _bucket_axis / _bucketize），不依赖 SQLite strftime。
空库 → 全 0 + 空数组，端点永远 200。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..models import TokenUsage
from ..schemas import (
    UsageBucket,
    UsageGroupStat,
    UsageSeries,
    UsageSummaryOut,
    UsageTimeseriesOut,
)
from ..services.usage import _bucket_axis, _bucketize

router = APIRouter(prefix="/api/usage", tags=["usage"])


def _label_for_path(path: str) -> str:
    """路径键 → 中文展示名（未知路径原样返回，便于排查未打标签的调用）。"""
    return models.PATH_LABEL.get(path, path or "未知")


def _filtered_rows(
    db: Session,
    user_id: str,
    *,
    path: str | None,
    model: str | None,
    provider: str | None,
) -> list[TokenUsage]:
    """按 user_id（强制）+ 可选筛选取出全部明细行（统计量级小，一次取回内存聚合）。"""
    stmt = select(TokenUsage).where(TokenUsage.user_id == user_id)
    if path:
        stmt = stmt.where(TokenUsage.path == path)
    if model:
        stmt = stmt.where(TokenUsage.model == model)
    if provider:
        stmt = stmt.where(TokenUsage.provider == provider)
    return list(db.scalars(stmt).all())


@router.get("/timeseries", response_model=UsageTimeseriesOut)
def usage_timeseries(
    granularity: str = Query("day"),
    tz_offset: int = Query(0, description="客户端时区相对 UTC 的分钟偏移（如东八区=480）"),
    group_by: str = Query("none"),
    path: str | None = Query(None),
    model: str | None = Query(None),
    provider: str | None = Query(None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> UsageTimeseriesOut:
    """三类 token 的时间序列：全局共享桶轴 + 每序列逐桶对齐补零。

    group_by=none 也返回 series 长度=1（key='all', label='全部'）。
    三档：day=过去24h按本地整点小时(24桶)；week=过去7天按本地日(7桶)；month=过去30天按本地日(30桶)。
    """
    if granularity not in ("day", "week", "month"):
        granularity = "day"
    if group_by not in ("none", "model", "path"):
        group_by = "none"

    rows = _filtered_rows(db, user_id, path=path, model=model, provider=provider)

    now_utc = datetime.now(timezone.utc)
    bucket_starts = _bucket_axis(rows, granularity, tz_offset, now_utc)
    bucket_iso = [b.isoformat() for b in bucket_starts]

    # 按 group_by 分组：none→一条 all；model→按模型；path→按路径
    groups: dict[str, list[TokenUsage]] = {}
    if group_by == "none":
        groups["all"] = rows
    elif group_by == "model":
        for r in rows:
            groups.setdefault(r.model or "", []).append(r)
    else:  # path
        for r in rows:
            groups.setdefault(r.path or "unknown", []).append(r)

    series: list[UsageSeries] = []
    if group_by == "none":
        bucketed = _bucketize(rows, bucket_starts, granularity, tz_offset)
        series.append(
            UsageSeries(
                key="all",
                label="全部",
                provider="",
                buckets=[
                    UsageBucket(bucket_start=bucket_iso[i], **bucketed[i])
                    for i in range(len(bucket_starts))
                ],
            )
        )
    else:
        for key, grows in groups.items():
            if group_by == "model":
                label = key or "（默认模型）"
                # 同一模型可能跨 provider，取首行 provider 作展示（统计口径足够）
                series_provider = grows[0].provider if grows else ""
            else:  # path
                label = _label_for_path(key)
                series_provider = ""
            bucketed = _bucketize(grows, bucket_starts, granularity, tz_offset)
            series.append(
                UsageSeries(
                    key=key,
                    label=label,
                    provider=series_provider,
                    buckets=[
                        UsageBucket(bucket_start=bucket_iso[i], **bucketed[i])
                        for i in range(len(bucket_starts))
                    ],
                )
            )

    return UsageTimeseriesOut(
        granularity=granularity,
        group_by=group_by,
        bucket_starts=bucket_iso,
        series=series,
    )


@router.get("/summary", response_model=UsageSummaryOut)
def usage_summary(
    path: str | None = Query(None),
    model: str | None = Query(None),
    provider: str | None = Query(None),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> UsageSummaryOut:
    """汇总：总量 + 按模型 + 按路径分组。各组按 input_miss 降序（最该优化的浮顶）。

    空库 → 全 0 + 空数组。calls=该组行数。by_path 的 provider 为空。
    """
    rows = _filtered_rows(db, user_id, path=path, model=model, provider=provider)

    total_hit = sum(int(r.input_hit or 0) for r in rows)
    total_miss = sum(int(r.input_miss or 0) for r in rows)
    total_output = sum(int(r.output or 0) for r in rows)
    total_calls = len(rows)

    def _aggregate(key_fn, provider_blank: bool) -> dict[str, dict]:
        acc: dict[str, dict] = {}
        for r in rows:
            k = key_fn(r)
            slot = acc.setdefault(
                k,
                {
                    "input_hit": 0,
                    "input_miss": 0,
                    "output": 0,
                    "calls": 0,
                    "provider": "" if provider_blank else (r.provider or ""),
                },
            )
            slot["input_hit"] += int(r.input_hit or 0)
            slot["input_miss"] += int(r.input_miss or 0)
            slot["output"] += int(r.output or 0)
            slot["calls"] += 1
        return acc

    model_acc = _aggregate(lambda r: r.model or "", provider_blank=False)
    path_acc = _aggregate(lambda r: r.path or "unknown", provider_blank=True)

    by_model = [
        UsageGroupStat(
            key=k,
            label=k or "（默认模型）",
            provider=v["provider"],
            input_hit=v["input_hit"],
            input_miss=v["input_miss"],
            output=v["output"],
            calls=v["calls"],
        )
        for k, v in model_acc.items()
    ]
    by_path = [
        UsageGroupStat(
            key=k,
            label=_label_for_path(k),
            provider="",
            input_hit=v["input_hit"],
            input_miss=v["input_miss"],
            output=v["output"],
            calls=v["calls"],
        )
        for k, v in path_acc.items()
    ]
    # 按 input_miss 降序：未命中输入是最该优化的浮顶
    by_model.sort(key=lambda s: s.input_miss, reverse=True)
    by_path.sort(key=lambda s: s.input_miss, reverse=True)

    return UsageSummaryOut(
        total_input_hit=total_hit,
        total_input_miss=total_miss,
        total_output=total_output,
        total_calls=total_calls,
        by_model=by_model,
        by_path=by_path,
    )
