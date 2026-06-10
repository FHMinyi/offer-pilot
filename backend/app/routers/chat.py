"""对话 Agent 路由：流式 SSE 接口。

POST /api/chat/stream 返回 text/event-stream，逐条产出 status/delta/tool_call/
tool_result/report/done/error 事件，让前端实时呈现 AI 的处理过程与输出。
"""

from __future__ import annotations

import contextvars
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..database import SessionLocal
from ..deps import get_current_user
from ..schemas import ChatRequest
from ..services import agent, llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> StreamingResponse:
    messages = [m.model_dump() for m in payload.messages]
    context = payload.context.model_dump()
    reasoning_effort = payload.reasoning_effort
    client_time = payload.client_time
    # 按请求覆盖 LLM 配置：仅保留非空字段，全空则视作 None（回退服务端 .env）
    override = payload.llm_override.model_dump() if payload.llm_override else None
    if override:
        override = {k: v for k, v in override.items() if v} or None

    def event_gen():
        # 在生成器内创建会话，保证整个流式过程中会话有效；
        # user_id 在路由层依赖解出后显式穿透（chat.py 生成器脱离请求依赖，§5.3）
        db = SessionLocal()
        # 用专属 context 承载「按请求覆盖」：在 ctx 内设一次覆盖，并用同一 ctx 驱动
        # 内层生成器的每一步（ctx.run(next, inner)）。Starlette 以线程池逐步迭代同步
        # 生成器，每次 next() 可能在不同线程/context——若用 with/Token 方案会跨 context
        # reset 而报错，且覆盖无法可靠跨 yield 传播；显式 ctx 则全程可见、无需重置。
        ctx = contextvars.copy_context()
        ctx.run(llm.set_override, override)
        try:
            inner = agent.run_turn(
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
            "X-Accel-Buffering": "no",  # 禁用反代缓冲，保证及时下发
        },
    )
