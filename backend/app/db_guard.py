"""Schema 守门：对照 ORM 声明的表/列与库中实际表/列，缺失则告警（绝不抛）。

里程碑一过渡设施，替代 Alembic 的零成本一致性校验。`init_db()` 的 `create_all`
只建缺失表、**绝不 ALTER 旧表**，故：
- 表级：检测「声明了但库里没有的表」（纯新增表会被 create_all 自动补齐）。
- 列级：检测「已存在表里缺失的声明列」。这是真正的坑——给旧表加列时 create_all
  不会补列，运行时直到首个查询才报 `no such column`；这里把它前移到启动期暴露。
两级均**仅告警不阻断启动**（对齐 main.py lifespan 只 init_db、无迁移工具的硬约束）。
里程碑三引入 Alembic 时，本模块可平移为迁移一致性校验。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect

from .database import Base, engine

logger = logging.getLogger("offerpilot.db_guard")

# 里程碑一完成后应有 8 张表 = 现有 5（resumes / job_postings / analysis_runs /
# conversations / saved_jds）+ 新增 3（journey_states / tasks / check_ins）。
# 期望集以 Base.metadata 为权威来源（自动随模型增减），本常量仅作文档化基线对照。
MILESTONE1_TABLES = {
    "resumes",
    "job_postings",
    "analysis_runs",
    "conversations",
    "saved_jds",
    "journey_states",
    "tasks",
    "check_ins",
}


def verify_schema(bind=None) -> dict:
    """对照 Base.metadata 声明的表/列与库中实际表/列，返回校验报告；缺失仅告警。

    返回 dict：{ok, expected, actual, missing, missing_columns}。绝不抛异常。
    """
    bind = bind or engine
    # 确保所有模型已注册到 metadata（与 init_db 同款导入）。
    from . import models  # noqa: F401

    inspector = inspect(bind)
    expected = set(Base.metadata.tables.keys())
    actual = set(inspector.get_table_names())
    missing = sorted(expected - actual)

    # 列级漂移：对既声明又存在的表，比对声明列与库中实际列，缺列单独告警。
    # 根因——create_all 只建缺失表、不 ALTER 旧表，给旧表加列在已有库里会静默缺失。
    missing_columns: dict[str, list[str]] = {}
    for tname in expected & actual:
        declared = set(Base.metadata.tables[tname].columns.keys())
        present = {c["name"] for c in inspector.get_columns(tname)}
        gap = sorted(declared - present)
        if gap:
            missing_columns[tname] = gap

    report = {
        "ok": not missing and not missing_columns,
        "expected": sorted(expected),
        "actual": sorted(actual),
        "missing": missing,
        "missing_columns": missing_columns,
    }
    if missing:
        logger.warning(
            "verify_schema: 缺失已声明的表 %s（声明 %d / 实际 %d，仅告警不阻断）",
            missing,
            len(expected),
            len(actual),
        )
    if missing_columns:
        logger.warning(
            "verify_schema: 已存在表缺失已声明的列 %s（create_all 不 ALTER 旧表，"
            "需手动迁移或删库重建；仅告警不阻断）",
            missing_columns,
        )
    if not missing and not missing_columns:
        logger.info("verify_schema OK（%d 张表、列齐全）", len(expected))
    return report
