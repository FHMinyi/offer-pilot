"""Schema 守门：对照 ORM 声明的表与库中实际表，缺失则告警（绝不抛）。

里程碑一过渡设施，替代 Alembic 的零成本一致性校验。本期全是纯新增表、
`init_db()` 的 `create_all` 只建缺失表、绝不 ALTER 旧表，故这里只做
「声明了但库里没有」的漂移检测，**仅告警不阻断启动**（对齐 main.py lifespan
只 init_db、无迁移工具的硬约束）。里程碑三引入 Alembic 时，本模块的期望表
清单可平移为迁移一致性校验。
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
    """对照 Base.metadata 声明的表与库中实际表，返回校验报告；缺失仅告警。

    返回 dict：{ok, expected, actual, missing}。绝不抛异常。
    """
    bind = bind or engine
    # 确保所有模型已注册到 metadata（与 init_db 同款导入）。
    from . import models  # noqa: F401

    expected = set(Base.metadata.tables.keys())
    actual = set(inspect(bind).get_table_names())
    missing = sorted(expected - actual)
    report = {
        "ok": not missing,
        "expected": sorted(expected),
        "actual": sorted(actual),
        "missing": missing,
    }
    if missing:
        logger.warning(
            "verify_schema: 缺失已声明的表 %s（声明 %d / 实际 %d，仅告警不阻断）",
            missing,
            len(expected),
            len(actual),
        )
    else:
        logger.info("verify_schema OK（%d 张表已就位）", len(expected))
    return report
