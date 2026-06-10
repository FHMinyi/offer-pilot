"""LLM 配置路由：从前端所填端点拉取可用模型列表（兼连通性测试）。

POST /api/llm/models 用请求体（而非 URL/query）携带 provider/base_url/API Key，
按 provider 复用 services.llm._build_client（带代理容错）调用上游 /models，
返回可选模型列表供前端下拉；任何异常一律降级为 {"ok": false, ...}，绝不抛 5xx，
让前端优雅退回纯手输。注意：全程不 log API Key。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..deps import get_current_user
from ..schemas import LLMOverrideIn
from ..services.llm import _build_client

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.post("/models")
def list_models(
    payload: LLMOverrideIn,
    user_id: str = Depends(get_current_user),
) -> dict:
    """从所填端点拉取可用模型列表。

    成功返回 {"ok": True, "models": [...]}；任何异常（SDK 未安装、鉴权失败、
    不支持 models 等）一律返回 {"ok": False, "error": ..., "models": []}，不抛 5xx。
    """
    settings = get_settings()
    provider = (payload.provider or settings.llm_provider).lower()

    try:
        if provider == "openai":
            from openai import OpenAI  # 延迟导入，未安装时落入 except 降级

            client = _build_client(
                OpenAI,
                api_key=payload.api_key or settings.openai_api_key or "not-needed",
                base_url=payload.base_url or settings.openai_base_url or None,
            )
            models = [m.id for m in client.models.list()]
        elif provider == "anthropic":
            import anthropic  # 延迟导入，未安装时落入 except 降级

            client = _build_client(
                anthropic.Anthropic,
                api_key=payload.api_key or settings.anthropic_api_key or "not-needed",
                base_url=payload.base_url or settings.anthropic_base_url or None,
            )
            listed = client.models.list()
            # anthropic SDK 的 models.list() 返回分页对象（有 .data），兼容可直接迭代的情况
            items = getattr(listed, "data", None) or listed
            models = [m.id for m in items]
        else:
            raise ValueError(f"不支持的 provider: {provider}")
    except Exception as exc:  # noqa: BLE001 一律降级，不抛 5xx，让前端退回手输（不 log Key）
        return {"ok": False, "error": str(exc), "models": []}

    return {"ok": True, "models": models}
