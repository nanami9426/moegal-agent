from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import UserMemory, utc_now
from db.session import get_engine


MEMORY_KINDS = {"profile", "preference", "dislike", "note"}


@dataclass(frozen=True)
class MemoryResult:
    memory: UserMemory
    created: bool
    reactivated: bool = False


def remember_memory(
    user_id: int,
    key: str,
    content: str,
    *,
    kind: str = "note",
) -> MemoryResult:
    memory_kind = _normalize_kind(kind)
    memory_key = _normalize_key(key)
    memory_content = content.strip()

    if not memory_key:
        raise ValueError("memory key is required.")
    if not memory_content:
        raise ValueError("memory content is required.")

    with Session(get_engine()) as session:
        memory = session.exec(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.kind == memory_kind,
                UserMemory.key == memory_key,
            )
        ).first()

        now = utc_now()
        if memory is not None:
            was_inactive = not memory.is_active
            memory.content = memory_content
            memory.is_active = True
            memory.updated_at = now
            session.add(memory)
            session.commit()
            session.refresh(memory)
            return MemoryResult(
                memory=memory,
                created=False,
                reactivated=was_inactive,
            )

        memory = UserMemory(
            user_id=user_id,
            kind=memory_kind,
            key=memory_key,
            content=memory_content,
            created_at=now,
            updated_at=now,
        )
        session.add(memory)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            memory = session.exec(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.kind == memory_kind,
                    UserMemory.key == memory_key,
                )
            ).one()
            was_inactive = not memory.is_active
            memory.content = memory_content
            memory.is_active = True
            memory.updated_at = now
            session.add(memory)
            session.commit()
            session.refresh(memory)
            return MemoryResult(
                memory=memory,
                created=False,
                reactivated=was_inactive,
            )

        session.refresh(memory)
        return MemoryResult(memory=memory, created=True)


def forget_memory(user_id: int, key: str, *, kind: str | None = None) -> int:
    memory_key = _normalize_key(key)
    if not memory_key:
        raise ValueError("memory key is required.")

    with Session(get_engine()) as session:
        query = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == memory_key,
            UserMemory.is_active == True,  # noqa: E712
        )
        if kind:
            query = query.where(UserMemory.kind == _normalize_kind(kind))

        memories = session.exec(query).all()
        if not memories:
            return 0

        now = utc_now()
        for memory in memories:
            memory.is_active = False
            memory.updated_at = now
            session.add(memory)
        session.commit()
        return len(memories)


def list_memories(user_id: int, *, limit: int = 20) -> list[UserMemory]:
    safe_limit = max(1, min(limit, 50))
    with Session(get_engine()) as session:
        return list(
            session.exec(
                select(UserMemory)
                .where(
                    UserMemory.user_id == user_id,
                    UserMemory.is_active == True,  # noqa: E712
                )
                .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
                .limit(safe_limit)
            ).all()
        )


def build_memory_context(user_id: int, *, limit: int = 20) -> str:
    memories = list_memories(user_id, limit=limit)
    if not memories:
        return ""

    return "\n".join(
        f"- kind={memory.kind}; key={memory.key}; content={memory.content}"
        for memory in memories
    )


def _normalize_kind(kind: str | None) -> str:
    memory_kind = (kind or "note").strip().lower()
    if memory_kind not in MEMORY_KINDS:
        return "note"
    return memory_kind


def _normalize_key(key: str) -> str:
    return " ".join(key.strip().split()).lower()[:128]
