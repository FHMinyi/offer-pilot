"""对话 Agent 路由 · **LangGraph 对照小样**：流式 SSE 接口（隔离 / 可选）。

POST /api/chat/stream_lab —— 与 /api/chat/stream 完全同构的事件流（status/delta/
tool_call/tool_result/report/usage/done/error），但编排走 services.agent_langgraph
的 LangGraph 实现。请求/响应契约与主端点一致，前端可原样切换调用以做对照。

驱动方式与 routers/chat.py 完全相同（专属 contextvars context 承载 LLM override 与
用量归属，再用同一 context 逐步迭代同步生成器）；仅把 agent.run_turn 换成
agent_langgraph.run_turn。未安装实验依赖时该端点优雅降级为一条提示，不影响主端点。
"""

from __future__ import annotations

import contextvars
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..database import SessionLocal
from ..deps import get_current_user
from ..schemas import ChatRequest
from ..services import agent_langgraph, llm, usage

router = APIRouter(prefix="/api/chat", tags=["chat-lab"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream_lab")
def chat_stream_lab(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    messages = [m.model_dump() for m in payload.messages]
    context = payload.context.model_dump()
    reasoning_effort = payload.reasoning_effort
    client_time = payload.client_time
    override = payload.llm_override.model_dump() if payload.llm_override else None
    if override:
        override = {k: v for k, v in override.items() if v} or None

    def event_gen():
        db = SessionLocal()
        # 专属 context：与 chat.py 同构地承载「按请求覆盖」与用量归属（path=chat + user_id），
        # 让小样内部 _dispatch_tool→pipeline 的解析用量与主端点一致地归属落库。
        ctx = contextvars.copy_context()
        ctx.run(llm.set_override, override)
        ctx.run(usage.set_usage_context, {"path": "chat", "user_id": user_id})
        try:
            inner = agent_langgraph.run_turn(
                messages, context, db, reasoning_effort, client_time, user_id=user_id
            )
            while True:
                try:
                    event, data = ctx.run(next, inner)
                except StopIteration:
                    break
                yield _sse(event, data)
        except Exception as exc:  # noqa: BLE001 兜底，避免流中断后前端无提示
            yield _sse("error", {"message": str(exc)})
        finally:
            db.close()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
