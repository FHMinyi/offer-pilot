"""联网搜索服务（Tavily）。

用于让分析跟上较新的岗位方向与框架（例如 AI Agent 开发常默认要求
LangChain/LangGraph/RAG/向量库，而 JD 未必写明）。

网络出口策略（重要）：
- 显式通过 httpx 的 proxy 参数走代理，并设置 trust_env=False，
  从而【只】使用我们选定的 http(s) 代理，刻意绕开环境中可能格式有误的
  ALL_PROXY/socks 变量。
- 全程只读取、不修改任何环境变量。
- 未配置 TAVILY_API_KEY 时优雅降级（返回空结果），Agent 改为仅凭已有知识作答。
"""

from __future__ import annotations

import os

from ..config import get_settings

settings = get_settings()

_TAVILY_URL = "https://api.tavily.com/search"


def _proxy() -> str | None:
    """选择出网代理：优先配置项，其次环境中的 http(s) 代理（不取 ALL_PROXY/socks）。"""
    if settings.search_proxy:
        return settings.search_proxy
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or None
    )


def search_enabled() -> bool:
    return bool(settings.tavily_api_key)


def web_search(query: str, max_results: int = 5) -> tuple[list[dict], str]:
    """执行一次联网搜索。

    返回 (results, 简短摘要)。results 为 [{title, url, content}]。
    未配置或失败时返回空列表与说明，调用方据此降级。
    """
    if not settings.tavily_api_key:
        return [], "（未配置联网搜索，基于已有知识作答）"

    import httpx

    try:
        with httpx.Client(trust_env=False, proxy=_proxy(), timeout=20.0) as client:
            resp = client.post(
                _TAVILY_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 搜索失败不应中断对话
        return [], f"搜索失败：{exc}"

    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        }
        for item in data.get("results", [])
    ]
    return results, f"找到 {len(results)} 条结果"


def results_to_text(query: str, results: list[dict]) -> str:
    """把搜索结果整理成喂给模型的文本。"""
    if not results:
        return f"（搜索“{query}”无结果或未配置联网搜索，请基于你已有的知识作答。）"
    lines = [
        f"- {r['title']}：{r['content'][:300]}（来源：{r['url']}）" for r in results
    ]
    return f"搜索“{query}”的网页摘要如下：\n" + "\n".join(lines)
