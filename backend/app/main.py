"""OfferPilot 后端入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .database import init_db
from .db_guard import verify_schema
from .routers import (
    analysis,
    chat,
    checkins,
    conversations,
    interviews,
    jobs,
    journey,
    llm,
    mastery,
    progress,
    resumes,
    saved_jds,
    skills,
    tasks,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建表（MVP 不引入迁移工具）
    init_db()
    # schema 守门：对照声明表与实际表，缺失仅告警不阻断（详见 db_guard.py）
    verify_schema()
    yield


app = FastAPI(
    title="OfferPilot API",
    version=__version__,
    description="面向应届生/实习求职者的 AI 求职规划工具后端。",
    lifespan=lifespan,
)

# CORS：CORS_ORIGINS=* 时放开任意来源（便于远程调试，此时不带凭据）；
# 否则按白名单。注意：前端经 Vite 代理访问时本就是同源，无需 CORS。
if "*" in settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(resumes.router)
app.include_router(jobs.router)
app.include_router(analysis.router)
app.include_router(skills.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(saved_jds.router)
app.include_router(tasks.router)
app.include_router(checkins.router)
app.include_router(journey.router)
app.include_router(progress.router)
app.include_router(interviews.router)
app.include_router(mastery.router)
app.include_router(llm.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """健康检查，同时暴露当前解析引擎，方便前端/运维确认是否启用了 LLM。"""
    from .services.llm import engine_name

    return {"status": "ok", "version": __version__, "engine": engine_name()}
