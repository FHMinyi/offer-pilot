"""pytest 公共夹具：使用临时 SQLite 库，避免污染开发数据库。"""

from __future__ import annotations

import os
import tempfile

import pytest

# 必须在导入应用之前设置，确保 get_settings() 读到测试库路径
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="offerpilot_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["LLM_PROVIDER"] = "none"  # 测试固定走规则模式，保证确定性


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    """会话级建表：让直连 SessionLocal 的用例（不经 client 夹具）也能独立运行，
    不再隐式依赖「先跑过某个 client 用例触发 lifespan 建表」的副作用。"""
    from app.database import init_db

    init_db()
    yield


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    os.close(_DB_FD)
    if os.path.exists(_DB_PATH):
        os.remove(_DB_PATH)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:  # with 触发 lifespan，自动建表
        yield c
