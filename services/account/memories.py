from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import (
    Conversation,
    MemoryConsolidationCursor,
    Message,
    UserMemoryDocument,
    UserMemorySettings,
    utc_now,
)
from db.session import get_engine


MAX_MEMORY_DOCUMENT_CHARS = 16_000


def get_memory_settings(user_id: int) -> UserMemorySettings:
    """读取用户设置；新用户首次访问时创建默认配置。"""
    with Session(get_engine()) as session:
        settings = session.get(UserMemorySettings, user_id)
        if settings is None:
            settings = UserMemorySettings(user_id=user_id)
            session.add(settings)
            try:
                session.commit()
            except IntegrityError:
                # 同一用户并发首个请求时，使用另一个事务刚创建的记录。
                session.rollback()
                settings = session.get(UserMemorySettings, user_id)
                if settings is None:
                    raise
            session.refresh(settings)
        return settings


def update_memory_settings(
    user_id: int,
    *,
    enabled: bool | None = None,
    auto_extract: bool | None = None,
) -> UserMemorySettings:
    with Session(get_engine()) as session:
        settings = session.get(UserMemorySettings, user_id)
        if settings is None:
            settings = UserMemorySettings(user_id=user_id)
        if enabled is not None:
            settings.enabled = enabled
        if auto_extract is not None:
            settings.auto_extract = auto_extract
        settings.updated_at = utc_now()
        session.add(settings)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            settings = session.get(UserMemorySettings, user_id)
            if settings is None:
                raise
            if enabled is not None:
                settings.enabled = enabled
            if auto_extract is not None:
                settings.auto_extract = auto_extract
            settings.updated_at = utc_now()
            session.add(settings)
            session.commit()
        session.refresh(settings)
        return settings


def get_memory_document(user_id: int) -> UserMemoryDocument:
    """取得用户唯一的 Markdown 记忆文档，不存在时创建空文档。"""
    with Session(get_engine()) as session:
        document = session.get(UserMemoryDocument, user_id)
        if document is None:
            document = UserMemoryDocument(user_id=user_id)
            session.add(document)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                document = session.get(UserMemoryDocument, user_id)
                if document is None:
                    raise
            session.refresh(document)
        return document


def update_memory_document(user_id: int, content: str) -> UserMemoryDocument:
    """替换完整 Markdown，并把当前已有聊天视为已由用户人工处理。"""
    normalized = normalize_memory_markdown(content)
    with Session(get_engine()) as session:
        document = session.get(UserMemoryDocument, user_id)
        now = utc_now()
        if document is None:
            document = UserMemoryDocument(
                user_id=user_id,
                content=normalized,
                created_at=now,
                updated_at=now,
            )
        else:
            document.content = normalized
            document.updated_at = now
        session.add(document)
        _advance_consolidation_cursors(session, user_id=user_id, now=now)
        try:
            session.commit()
        except IntegrityError:
            # 后台任务可能刚创建了空文档；用户保存的版本应作为最终结果。
            session.rollback()
            document = session.get(UserMemoryDocument, user_id)
            if document is None:
                raise
            document.content = normalized
            document.updated_at = now
            session.add(document)
            _advance_consolidation_cursors(session, user_id=user_id, now=now)
            session.commit()
        session.refresh(document)
        return document


def clear_memory_document(user_id: int) -> UserMemoryDocument:
    return update_memory_document(user_id, "")


def build_memory_context(user_id: int) -> str:
    """返回整份 Markdown 记忆；文档本身受统一长度上限约束。"""
    document = get_memory_document(user_id)
    return document.content.strip()


def normalize_memory_markdown(content: str) -> str:
    normalized = content.strip()
    if len(normalized) > MAX_MEMORY_DOCUMENT_CHARS:
        raise ValueError(
            f"memory document exceeds {MAX_MEMORY_DOCUMENT_CHARS} characters."
        )
    return normalized


def _advance_consolidation_cursors(
    session: Session,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """防止人工删改后，历史未处理消息把旧事实重新写回文档。"""
    latest_messages = session.exec(
        select(Message.conversation_id, func.max(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id)
        .group_by(Message.conversation_id)
    ).all()
    for conversation_id, source_message_id in latest_messages:
        cursor = session.get(MemoryConsolidationCursor, conversation_id)
        if cursor is None:
            cursor = MemoryConsolidationCursor(
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                created_at=now,
                updated_at=now,
            )
        else:
            cursor.source_message_id = source_message_id
            cursor.updated_at = now
        session.add(cursor)
