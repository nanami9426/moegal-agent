from dataclasses import dataclass

from sqlmodel import Session, select

from db.models import ConversationMemory, utc_now
from db.session import get_engine
from services.account.memories import calculate_text_relevance


@dataclass(frozen=True)
class EpisodeMatch:
    memory: ConversationMemory
    score: float


def get_conversation_memory(conversation_id: int) -> ConversationMemory | None:
    with Session(get_engine()) as session:
        return session.exec(
            select(ConversationMemory).where(
                ConversationMemory.conversation_id == conversation_id,
            )
        ).first()


def upsert_conversation_memory(
    *,
    conversation_id: int,
    user_id: int,
    namespace: str,
    title: str,
    summary: str,
    topics: list[str],
    open_items: list[str],
    source_message_id: int | None,
) -> ConversationMemory:
    normalized_summary = summary.strip()
    if not normalized_summary:
        raise ValueError("conversation summary is required.")

    with Session(get_engine()) as session:
        memory = session.exec(
            select(ConversationMemory).where(
                ConversationMemory.conversation_id == conversation_id,
            )
        ).first()
        now = utc_now()
        if memory is None:
            memory = ConversationMemory(
                conversation_id=conversation_id,
                user_id=user_id,
                namespace=namespace[:255],
                title=title.strip()[:255] or "未命名会话",
                summary=normalized_summary,
                topics=_normalize_items(topics, limit=12),
                open_items=_normalize_items(open_items, limit=12),
                source_message_id=source_message_id,
                created_at=now,
                updated_at=now,
            )
        else:
            memory.namespace = namespace[:255]
            memory.title = title.strip()[:255] or memory.title
            memory.summary = normalized_summary
            memory.topics = _normalize_items(topics, limit=12)
            memory.open_items = _normalize_items(open_items, limit=12)
            memory.source_message_id = source_message_id
            memory.is_active = True
            memory.updated_at = now
        session.add(memory)
        session.commit()
        session.refresh(memory)
        return memory


def retrieve_conversation_memories(
    user_id: int,
    query: str,
    *,
    namespaces: list[str] | None = None,
    exclude_conversation_id: int | None = None,
    limit: int = 2,
) -> list[EpisodeMatch]:
    safe_limit = max(1, min(limit, 10))
    with Session(get_engine()) as session:
        statement = select(ConversationMemory).where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.is_active == True,  # noqa: E712
        )
        if namespaces:
            statement = statement.where(ConversationMemory.namespace.in_(namespaces))
        if exclude_conversation_id is not None:
            statement = statement.where(
                ConversationMemory.conversation_id != exclude_conversation_id,
            )
        rows = session.exec(
            statement.order_by(
                ConversationMemory.updated_at.desc(),
                ConversationMemory.id.desc(),
            ).limit(100)
        ).all()

    matches: list[EpisodeMatch] = []
    for memory in rows:
        search_content = " ".join(
            [memory.summary, *memory.topics, *memory.open_items]
        )
        relevance = calculate_text_relevance(
            query,
            key=memory.title,
            content=search_content,
            kind="note",
        )
        if query.strip() and relevance <= 0:
            continue
        matches.append(EpisodeMatch(memory=memory, score=relevance))
    matches.sort(
        key=lambda match: (
            match.score,
            match.memory.updated_at,
            match.memory.id or 0,
        ),
        reverse=True,
    )
    return matches[:safe_limit]


def _normalize_items(items: list[str], *, limit: int) -> list[str]:
    normalized: list[str] = []
    for item in items:
        text = " ".join(str(item).strip().split())[:255]
        if text and text not in normalized:
            normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized
