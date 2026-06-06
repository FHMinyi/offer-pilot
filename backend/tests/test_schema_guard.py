"""里程碑一 · C0 接缝与守门设施测试。

覆盖 deps.get_current_user 归属接缝、ownership 单点防越权「形」（本期放行）、
db_guard.verify_schema 一致性守门。C1 加表后会在此追加「新增 3 表已就位」断言。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db_guard import verify_schema
from app.deps import DEFAULT_USER, get_current_user
from app.ownership import require_owned, scope_to_user


def test_get_current_user_default_when_absent():
    assert get_current_user(None) == DEFAULT_USER
    assert get_current_user("") == DEFAULT_USER
    assert get_current_user("   ") == DEFAULT_USER


def test_get_current_user_takes_device_id_trimmed_and_capped():
    assert get_current_user("dev-abc") == "dev-abc"
    assert get_current_user("  dev-abc  ") == "dev-abc"
    assert get_current_user("x" * 100) == "x" * 64  # String(64) 同形上限


def test_scope_to_user_passes_through_this_milestone():
    sentinel = object()
    assert scope_to_user(sentinel, object, "local") is sentinel


def test_require_owned_404_when_missing(client):
    # client 触发 lifespan 建表
    from app.database import SessionLocal
    from app.models import Resume

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as ei:
            require_owned(db, Resume, 999999, "local")
        assert ei.value.status_code == 404
    finally:
        db.close()


def test_require_owned_returns_existing_object(client):
    from app.database import SessionLocal
    from app.models import Resume

    db = SessionLocal()
    try:
        row = Resume(raw_text="hi", structured={}, source_type="paste")
        db.add(row)
        db.commit()
        db.refresh(row)
        got = require_owned(db, Resume, row.id, "local")
        assert got.id == row.id
    finally:
        db.close()


def test_verify_schema_ok_for_current_models(client):
    # client 已触发 init_db + create_all，全部已声明表应就位。
    report = verify_schema()
    assert report["ok"] is True, f"缺失表: {report['missing']}"
    assert report["missing"] == []
    # 现有 5 张核心表必须在期望与实际集合中。
    for t in ("resumes", "job_postings", "analysis_runs", "conversations", "saved_jds"):
        assert t in report["expected"]
        assert t in report["actual"]


def test_verify_schema_includes_milestone1_tables(client):
    # C1：三张状态表已入模型，create_all 应自动建出，metadata 恰覆盖 8 表基线。
    from app.db_guard import MILESTONE1_TABLES

    report = verify_schema()
    assert report["ok"] is True, f"缺失表: {report['missing']}"
    for t in ("journey_states", "tasks", "check_ins"):
        assert t in report["expected"]
        assert t in report["actual"]
    assert set(report["expected"]) == MILESTONE1_TABLES
