"""会话历史路由：保存 / 列出 / 读取完整对话。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation
from ..schemas import (
    ConversationOut,
    ConversationSaveOut,
    ConversationSaveRequest,
    ConversationSummaryOut,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationSaveOut)
def save_conversation(payload: ConversationSaveRequest, db: Session = Depends(get_db)) -> Conversation:
    """新建或更新会话（upsert）。"""
    title = (payload.title or "未命名对话")[:255]

    if payload.id is not None:
        conv = db.get(Conversation, payload.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        conv.title = title
        conv.turns = payload.turns  # 整体赋值，确保 JSON 变更被侦测
        conv.context = payload.context
    else:
        conv = Conversation(title=title, turns=payload.turns, context=payload.context)
        db.add(conv)

    db.commit()
    db.refresh(conv)
    return conv


@router.get("", response_model=list[ConversationSummaryOut])
def list_conversations(db: Session = Depends(get_db)) -> list[ConversationSummaryOut]:
    """会话列表（按更新时间倒序）。"""
    rows = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())).all()
    return [
        ConversationSummaryOut(
            id=c.id,
            title=c.title,
            turn_count=len(c.turns or []),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> Conversation:
    """读取单个会话的完整内容。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return conv
