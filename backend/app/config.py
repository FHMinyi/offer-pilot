"""应用配置：从环境变量 / .env 读取，全部带默认值，保证零配置可运行。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。"""

    # 数据库连接串，默认使用本地 SQLite
    database_url: str = "sqlite:///./offerpilot.db"

    # LLM 提供方：none / openai / anthropic
    # 解析协议：none / openai / anthropic
    # 这里的 openai / anthropic 指的是“API 协议”，而非必须使用它们家的模型。
    # 配合下方 base_url，可对接任意兼容该协议的服务（本地 vLLM/Ollama、DeepSeek、OpenRouter、Azure 等）。
    llm_provider: str = "none"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # 自定义服务端点（兼容协议时填写）；留空则使用官方默认地址
    openai_base_url: str = ""
    anthropic_base_url: str = ""
    # 模型名称（默认/对话/聚合总结用）。对接官方时可留空走内置默认；对接兼容服务时必须显式填写该服务的模型名
    llm_model: str = ""
    # 按任务分流的模型覆盖（留空则回退到 llm_model）：
    # llm_model_resume —— 解析简历；llm_model_jd —— 单条 JD 解析
    # 典型用法：解析简历/JD 用更快的小模型，对话/聚合总结用更强的大模型
    llm_model_resume: str = ""
    llm_model_jd: str = ""

    # 联网搜索（Tavily）。留空则不联网，Agent 仅凭已有知识作答。
    tavily_api_key: str = ""
    # 搜索出网代理。留空则自动复用环境中的 http(s) 代理（不会修改任何环境变量，
    # 且刻意绕开可能格式有误的 ALL_PROXY/socks 变量）。如需指定可填 http://host:port
    search_proxy: str = ""

    # 允许跨域的前端地址，逗号分隔
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """单例配置，避免重复读取 .env。"""
    return Settings()
