"""对话 Agent 路由：流式 SSE 接口。

POST /api/chat/stream 返回 text/event-stream，逐条产出 status/delta/tool_call/
tool_result/report/done/error 事件，让前端实时呈现 AI 的处理过程与输出。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..database import SessionLocal
from ..deps import get_current_user
from ..schemas import ChatRequest
from ..services import agent

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

    def event_gen():
        # 在生成器内创建会话，保证整个流式过程中会话有效；
        # user_id 在路由层依赖解出后显式穿透（chat.py 生成器脱离请求依赖，§5.3）
        db = SessionLocal()
        try:
            for event, data in agent.run_turn(
                messages, context, db, reasoning_effort, client_time, user_id=user_id
            ):
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
