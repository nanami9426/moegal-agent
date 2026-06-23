import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from db.models import Conversation, Message, utc_now
from db.session import get_engine


@dataclass(frozen=True)
class ConversationContext:
    # Session 关闭后只把路由层需要的不可变字段带出去。
    id: int
    thread_id: str
    version: int


def get_or_create_active_conversation(
    *,
    user_id: int,
    platform: str,
    platform_user_id: str,
) -> ConversationContext:
    platform = platform.strip()
    platform_user_id = str(platform_user_id).strip()
    if not platform or not platform_user_id:
        raise ValueError("platform and platform_user_id are required.")

    with Session(get_engine()) as session:
        # 普通消息始终复用当前 active 会话，实现重启后继续上下文。
        conversation = _get_active_conversation(session, platform, platform_user_id)
        now = utc_now()
        if conversation is not None:
            conversation.user_id = user_id
            conversation.updated_at = now
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return _to_context(conversation)

        # 用户第一次发消息时创建 v0 业务版本，并分配随机 UUID thread_id。
        version = _next_version(session, platform, platform_user_id, initial_version=0)
        conversation = Conversation(
            user_id=user_id,
            platform=platform,
            platform_user_id=platform_user_id,
            thread_id=_build_thread_id(),
            version=version,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return _to_context(conversation)


def start_new_conversation(
    *,
    user_id: int,
    platform: str,
    platform_user_id: str,
) -> ConversationContext:
    platform = platform.strip()
    platform_user_id = str(platform_user_id).strip()
    if not platform or not platform_user_id:
        raise ValueError("platform and platform_user_id are required.")

    with Session(get_engine()) as session:
        now = utc_now()
        # 兼容历史异常数据：如果有多条 active，会一次性全部结束。
        active_conversations = session.exec(
            select(Conversation).where(
                Conversation.platform == platform,
                Conversation.platform_user_id == platform_user_id,
                Conversation.is_active == True,  # noqa: E712
            )
        ).all()
        for conversation in active_conversations:
            conversation.is_active = False
            conversation.ended_at = now
            conversation.updated_at = now
            session.add(conversation)

        # /newchat 不删除旧记录，只创建下一个版本作为新的 active 会话。
        version = _next_version(session, platform, platform_user_id, initial_version=1)
        conversation = Conversation(
            user_id=user_id,
            platform=platform,
            platform_user_id=platform_user_id,
            thread_id=_build_thread_id(),
            version=version,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return _to_context(conversation)


def append_message(
    *,
    conversation_id: int,
    role: str,
    content: str | None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    now = utc_now()
    with Session(get_engine()) as session:
        # 写聊天日志时顺手刷新会话更新时间，便于后续按最近会话排序。
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = now
            session.add(conversation)

        session.add(
            Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata_json=metadata_json or {},
                created_at=now,
            )
        )
        session.commit()


def _get_active_conversation(
    session: Session,
    platform: str,
    platform_user_id: str,
) -> Conversation | None:
    return session.exec(
        select(Conversation)
        .where(
            Conversation.platform == platform,
            Conversation.platform_user_id == platform_user_id,
            Conversation.is_active == True,  # noqa: E712
        )
        .order_by(Conversation.version.desc())
    ).first()


def _next_version(
    session: Session,
    platform: str,
    platform_user_id: str,
    *,
    initial_version: int,
) -> int:
    # 版本号只在同一平台用户范围内递增，跨平台用户互不影响。
    current_max = session.exec(
        select(func.max(Conversation.version)).where(
            Conversation.platform == platform,
            Conversation.platform_user_id == platform_user_id,
        )
    ).one()
    if current_max is None:
        return initial_version
    return int(current_max) + 1


def _build_thread_id() -> str:
    # LangGraph 只要求 thread_id 唯一；使用 UUID 避免把平台用户信息暴露在 checkpoint 表中。
    return str(uuid.uuid4())


def _to_context(conversation: Conversation) -> ConversationContext:
    if conversation.id is None:
        raise RuntimeError("Conversation has not been persisted.")
    return ConversationContext(
        id=conversation.id,
        thread_id=conversation.thread_id,
        version=conversation.version,
    )
