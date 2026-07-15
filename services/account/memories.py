import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import (
    ConversationMemory,
    MemoryRevision,
    UserMemory,
    UserMemorySettings,
    utc_now,
)
from db.session import get_engine


MEMORY_KINDS = {"profile", "preference", "dislike", "note"}
MEMORY_SOURCES = {"explicit", "inferred", "summary", "legacy"}
DEFAULT_RETRIEVAL_LIMIT = 6
DEFAULT_CONTEXT_CHAR_BUDGET = 1600
MAX_RETRIEVAL_CANDIDATES = 200

# 当前查询出现这些意图时，优先召回对应类别；这是向量召回前的轻量实现。
KIND_QUERY_HINTS = {
    "profile": {"名字", "称呼", "叫我", "生日", "住在", "语言", "时区", "我是"},
    "preference": {"推荐", "喜欢", "偏好", "想看", "想玩", "动画", "漫画", "游戏", "音乐"},
    "dislike": {"不要", "不喜欢", "讨厌", "避雷", "剧透", "雷点", "推荐"},
    "note": {"上次", "之前", "继续", "计划", "目标", "提醒", "待办"},
}


@dataclass(frozen=True)
class MemoryResult:
    memory: UserMemory
    created: bool
    reactivated: bool = False


def get_memory_settings(user_id: int) -> UserMemorySettings:
    """读取用户记忆设置；首次访问时创建默认启用配置。"""
    with Session(get_engine()) as session:
        settings = session.get(UserMemorySettings, user_id)
        if settings is None:
            settings = UserMemorySettings(user_id=user_id)
            session.add(settings)
            try:
                session.commit()
            except IntegrityError:
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
    use_chat_history: bool | None = None,
) -> UserMemorySettings:
    with Session(get_engine()) as session:
        settings = session.get(UserMemorySettings, user_id)
        if settings is None:
            settings = UserMemorySettings(user_id=user_id)
        if enabled is not None:
            settings.enabled = enabled
        if auto_extract is not None:
            settings.auto_extract = auto_extract
        if use_chat_history is not None:
            settings.use_chat_history = use_chat_history
        settings.updated_at = utc_now()
        session.add(settings)
        session.commit()
        session.refresh(settings)
        return settings


def remember_memory(
    user_id: int,
    key: str,
    content: str,
    *,
    namespace: str = "global",
    kind: str = "note",
    source: str = "explicit",
    confidence: float = 1.0,
    importance: float = 0.5,
    source_message_id: int | None = None,
    expires_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    reason: str | None = None,
) -> MemoryResult:
    memory_kind = _normalize_kind(kind)
    memory_namespace = _normalize_namespace(namespace)
    memory_source = _normalize_source(source)
    memory_key = _normalize_key(key)
    memory_content = content.strip()
    memory_confidence = _normalize_score(confidence)
    memory_importance = _normalize_score(importance)

    if not memory_key:
        raise ValueError("memory key is required.")
    if not memory_content:
        raise ValueError("memory content is required.")

    with Session(get_engine()) as session:
        memory = session.exec(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.namespace == memory_namespace,
                UserMemory.kind == memory_kind,
                UserMemory.key == memory_key,
            )
        ).first()

        now = utc_now()
        if memory is not None:
            was_inactive = not memory.is_active
            previous_content = memory.content
            memory.content = memory_content
            memory.source = memory_source
            memory.confidence = memory_confidence
            memory.importance = memory_importance
            memory.source_message_id = source_message_id
            memory.expires_at = expires_at
            if metadata is not None:
                memory.metadata_json = dict(metadata)
            memory.is_active = True
            memory.updated_at = now
            session.add(memory)
            session.add(
                _build_revision(
                    memory=memory,
                    action="reactivate" if was_inactive else "update",
                    previous_content=previous_content,
                    source=memory_source,
                    reason=reason,
                )
            )
            session.commit()
            session.refresh(memory)
            return MemoryResult(
                memory=memory,
                created=False,
                reactivated=was_inactive,
            )

        memory = UserMemory(
            user_id=user_id,
            namespace=memory_namespace,
            kind=memory_kind,
            key=memory_key,
            content=memory_content,
            source=memory_source,
            confidence=memory_confidence,
            importance=memory_importance,
            source_message_id=source_message_id,
            expires_at=expires_at,
            metadata_json=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        session.add(memory)

        try:
            session.flush()
            session.add(
                _build_revision(
                    memory=memory,
                    action="create",
                    previous_content=None,
                    source=memory_source,
                    reason=reason,
                )
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            memory = session.exec(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.namespace == memory_namespace,
                    UserMemory.kind == memory_kind,
                    UserMemory.key == memory_key,
                )
            ).one()
            was_inactive = not memory.is_active
            previous_content = memory.content
            memory.content = memory_content
            memory.source = memory_source
            memory.confidence = memory_confidence
            memory.importance = memory_importance
            memory.source_message_id = source_message_id
            memory.expires_at = expires_at
            if metadata is not None:
                memory.metadata_json = dict(metadata)
            memory.is_active = True
            memory.updated_at = now
            session.add(memory)
            session.add(
                _build_revision(
                    memory=memory,
                    action="reactivate" if was_inactive else "update",
                    previous_content=previous_content,
                    source=memory_source,
                    reason=reason,
                )
            )
            session.commit()
            session.refresh(memory)
            return MemoryResult(
                memory=memory,
                created=False,
                reactivated=was_inactive,
            )

        session.refresh(memory)
        return MemoryResult(memory=memory, created=True)


def forget_memory(
    user_id: int,
    key: str,
    *,
    kind: str | None = None,
    namespace: str | None = None,
) -> int:
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
        if namespace:
            query = query.where(UserMemory.namespace == _normalize_namespace(namespace))

        memories = session.exec(query).all()
        if not memories:
            return 0

        now = utc_now()
        for memory in memories:
            memory.is_active = False
            memory.updated_at = now
            session.add(memory)
            session.add(
                _build_revision(
                    memory=memory,
                    action="forget",
                    previous_content=memory.content,
                    source="explicit",
                    reason="用户要求遗忘记忆",
                    content=None,
                )
            )
        session.commit()
        return len(memories)


def update_memory_by_id(
    user_id: int,
    memory_id: int,
    *,
    content: str | None = None,
    importance: float | None = None,
    confidence: float | None = None,
    expires_at: datetime | None = None,
    update_expires_at: bool = False,
) -> UserMemory | None:
    """按所有者更新一条记忆，供用户管理界面纠错。"""
    with Session(get_engine()) as session:
        memory = session.get(UserMemory, memory_id)
        if memory is None or memory.user_id != user_id or not memory.is_active:
            return None

        previous_content = memory.content
        if content is not None:
            normalized_content = content.strip()
            if not normalized_content:
                raise ValueError("memory content is required.")
            memory.content = normalized_content
        if importance is not None:
            memory.importance = _normalize_score(importance)
        if confidence is not None:
            memory.confidence = _normalize_score(confidence)
        if update_expires_at:
            memory.expires_at = expires_at
        memory.source = "explicit"
        memory.updated_at = utc_now()
        session.add(memory)
        session.add(
            _build_revision(
                memory=memory,
                action="user_update",
                previous_content=previous_content,
                source="explicit",
                reason="用户在记忆管理界面纠正",
            )
        )
        session.commit()
        session.refresh(memory)
        return memory


def forget_memory_by_id(user_id: int, memory_id: int) -> bool:
    with Session(get_engine()) as session:
        memory = session.get(UserMemory, memory_id)
        if memory is None or memory.user_id != user_id or not memory.is_active:
            return False
        memory.is_active = False
        memory.updated_at = utc_now()
        session.add(memory)
        session.add(
            _build_revision(
                memory=memory,
                action="forget",
                previous_content=memory.content,
                source="explicit",
                reason="用户在记忆管理界面删除",
                content=None,
            )
        )
        session.commit()
        return True


def forget_all_memories(user_id: int) -> int:
    with Session(get_engine()) as session:
        memories = session.exec(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.is_active == True,  # noqa: E712
            )
        ).all()
        now = utc_now()
        for memory in memories:
            memory.is_active = False
            memory.updated_at = now
            session.add(memory)
            session.add(
                _build_revision(
                    memory=memory,
                    action="forget",
                    previous_content=memory.content,
                    source="explicit",
                    reason="用户清空全部记忆",
                    content=None,
                )
            )
        # 清空长期记忆也应覆盖后台生成的情景摘要；原始聊天记录不受影响。
        conversation_memories = session.exec(
            select(ConversationMemory).where(
                ConversationMemory.user_id == user_id,
                ConversationMemory.is_active == True,  # noqa: E712
            )
        ).all()
        for conversation_memory in conversation_memories:
            conversation_memory.is_active = False
            conversation_memory.updated_at = now
            session.add(conversation_memory)
        if memories or conversation_memories:
            session.commit()
        return len(memories) + len(conversation_memories)


def list_memories(
    user_id: int,
    *,
    limit: int = 20,
    namespaces: list[str] | None = None,
) -> list[UserMemory]:
    safe_limit = max(1, min(limit, 50))
    now = utc_now()
    with Session(get_engine()) as session:
        query = select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.is_active == True,  # noqa: E712
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
        if namespaces:
            query = query.where(
                UserMemory.namespace.in_([_normalize_namespace(item) for item in namespaces])
            )
        memories = session.exec(
            query
            .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(safe_limit)
        ).all()
        return list(memories)


def retrieve_memories(
    user_id: int,
    query: str,
    *,
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
    namespaces: list[str] | None = None,
) -> list[UserMemory]:
    """根据本轮消息召回相关记忆，并记录实际使用次数。"""
    safe_limit = max(1, min(limit, 20))
    normalized_query = " ".join(query.strip().lower().split())
    now = utc_now()

    with Session(get_engine()) as session:
        candidates = _load_memory_candidates(
            session,
            user_id=user_id,
            query=normalized_query,
            namespaces=namespaces,
            now=now,
        )

        ranked: list[tuple[float, UserMemory]] = []
        for memory in candidates:
            if _is_expired(memory, now):
                continue
            relevance = _memory_relevance(normalized_query, memory)
            # 有查询时过滤明显无关的普通记忆；高重要度记忆仍保留候选资格。
            if normalized_query and relevance <= 0 and memory.importance < 0.85:
                continue
            score = _memory_score(memory, relevance=relevance, now=now)
            ranked.append((score, memory))

        ranked.sort(
            key=lambda item: (item[0], item[1].updated_at, item[1].id or 0),
            reverse=True,
        )
        selected = [memory for _, memory in ranked[:safe_limit]]
        for memory in selected:
            memory.last_accessed_at = now
            memory.access_count += 1
            session.add(memory)
        if selected:
            session.commit()
            # commit 默认会过期 ORM 字段，返回前刷新以便调用方在会话外安全读取。
            for memory in selected:
                session.refresh(memory)
        return selected


def build_memory_context(
    user_id: int,
    *,
    query: str = "",
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
    char_budget: int = DEFAULT_CONTEXT_CHAR_BUDGET,
    namespaces: list[str] | None = None,
    include_chat_history: bool = True,
    exclude_conversation_id: int | None = None,
) -> str:
    memories = retrieve_memories(
        user_id,
        query,
        limit=limit,
        namespaces=namespaces,
    )
    safe_budget = max(256, min(char_budget, 8000))
    items: list[dict[str, Any]] = [
        {
            "memory_type": "semantic",
            "kind": memory.kind,
            "namespace": memory.namespace,
            "key": memory.key,
            "content": memory.content,
            "source": memory.source,
            "confidence": round(memory.confidence, 2),
        }
        for memory in memories
    ]
    if include_chat_history:
        # 延迟导入避免语义记忆与情景记忆服务形成模块循环。
        from services.account.conversation_memories import (
            retrieve_conversation_memories,
        )

        episode_matches = retrieve_conversation_memories(
            user_id,
            query,
            namespaces=namespaces,
            exclude_conversation_id=exclude_conversation_id,
            limit=2,
        )
        items.extend(
            {
                "memory_type": "episode",
                "namespace": match.memory.namespace,
                "title": match.memory.title,
                "summary": match.memory.summary,
                "topics": match.memory.topics,
                "open_items": match.memory.open_items,
            }
            for match in episode_matches
        )
    if not items:
        return ""

    payload: list[dict[str, Any]] = []
    for item in items:
        candidate = json.dumps([*payload, item], ensure_ascii=False, separators=(",", ":"))
        if len(candidate) <= safe_budget:
            payload.append(item)
            continue
        if not payload:
            # 单条内容过长时保留结构和开头，确保上下文总量可控。
            content_field = "content" if "content" in item else "summary"
            payload.append(_fit_item_to_budget(item, safe_budget, content_field))
        break

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _normalize_kind(kind: str | None) -> str:
    memory_kind = (kind or "note").strip().lower()
    if memory_kind not in MEMORY_KINDS:
        return "note"
    return memory_kind


def _normalize_key(key: str) -> str:
    return " ".join(key.strip().split()).lower()[:128]


def _normalize_namespace(namespace: str | None) -> str:
    normalized = " ".join((namespace or "global").strip().split()).lower()
    return normalized[:255] or "global"


def _normalize_source(source: str | None) -> str:
    memory_source = (source or "inferred").strip().lower()
    if memory_source not in MEMORY_SOURCES:
        return "inferred"
    return memory_source


def _normalize_score(value: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(score):
        return 0.5
    return max(0.0, min(score, 1.0))


def _build_revision(
    *,
    memory: UserMemory,
    action: str,
    previous_content: str | None,
    source: str,
    reason: str | None,
    content: str | None = None,
) -> MemoryRevision:
    if memory.id is None:
        raise ValueError("memory must be flushed before creating a revision")
    return MemoryRevision(
        memory_id=memory.id,
        action=action,
        previous_content=previous_content,
        content=memory.content if content is None and action != "forget" else content,
        source=source,
        reason=(reason or "").strip()[:512] or None,
    )


def _is_expired(memory: UserMemory, now: datetime) -> bool:
    expires_at = memory.expires_at
    if expires_at is None:
        return False
    # SQLite 测试可能返回无时区 datetime，统一按 now 的时区比较。
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    return expires_at <= now


def _memory_relevance(query: str, memory: UserMemory) -> float:
    return calculate_text_relevance(
        query,
        key=memory.key,
        content=memory.content,
        kind=memory.kind,
    )


def calculate_text_relevance(
    query: str,
    *,
    key: str,
    content: str,
    kind: str,
) -> float:
    query = " ".join(query.strip().lower().split())
    if not query:
        return 0.2

    key = key.lower()
    content = content.lower()
    relevance = 0.0
    if key and key in query:
        relevance += 0.65
    if query in content or (len(content) >= 4 and content in query):
        relevance += 0.35

    query_terms = _search_terms(query)
    memory_terms = _search_terms(f"{key} {content}")
    if query_terms and memory_terms:
        overlap = len(query_terms & memory_terms) / len(query_terms)
        relevance += min(overlap, 1.0) * 0.45

    hints = KIND_QUERY_HINTS.get(kind, set())
    if any(hint in query for hint in hints):
        relevance += 0.25
    # 称呼等核心资料可以跨主题生效，但权重低于明确相关记忆。
    if kind == "profile" and key in {"nickname", "name", "称呼", "名字"}:
        relevance += 0.1
    return min(relevance, 1.0)


def _search_terms(text: str) -> set[str]:
    latin_terms = {
        term for term in re.findall(r"[a-z0-9_]+", text.lower()) if len(term) >= 2
    }
    cjk_terms: set[str] = set()
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        cjk_terms.update(
            sequence[index:index + 2]
            for index in range(max(0, len(sequence) - 1))
        )
    return latin_terms | cjk_terms


def _memory_score(memory: UserMemory, *, relevance: float, now: datetime) -> float:
    updated_at = memory.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=now.tzinfo)
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
    recency = 1 / (1 + age_days / 30)
    return (
        0.55 * relevance
        + 0.20 * memory.importance
        + 0.15 * memory.confidence
        + 0.10 * recency
    )


def _load_memory_candidates(
    session: Session,
    *,
    user_id: int,
    query: str,
    namespaces: list[str] | None,
    now: datetime,
) -> list[UserMemory]:
    conditions = [
        UserMemory.user_id == user_id,
        UserMemory.is_active == True,  # noqa: E712
        or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
    ]
    if namespaces:
        conditions.append(
            UserMemory.namespace.in_(
                [_normalize_namespace(item) for item in namespaces]
            )
        )

    # 一部分候选来自最近记忆，另一部分从全部历史做关键词检索，避免旧但相关的记忆
    # 因为更新时间不够新而永远无法进入排序。
    recent = session.exec(
        select(UserMemory)
        .where(*conditions)
        .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
        .limit(MAX_RETRIEVAL_CANDIDATES // 2)
    ).all()
    candidates = {memory.id: memory for memory in recent}

    search_terms = sorted(_search_terms(query), key=len, reverse=True)[:8]
    if search_terms:
        lexical_filters = []
        for term in search_terms:
            pattern = f"%{term}%"
            lexical_filters.extend(
                [UserMemory.key.ilike(pattern), UserMemory.content.ilike(pattern)]
            )
        lexical = session.exec(
            select(UserMemory)
            .where(*conditions, or_(*lexical_filters))
            .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(MAX_RETRIEVAL_CANDIDATES // 2)
        ).all()
        candidates.update({memory.id: memory for memory in lexical})

    if query and session.bind is not None and session.bind.dialect.name == "postgresql":
        namespace_filter = ""
        params: dict[str, Any] = {"user_id": user_id, "query": query}
        if namespaces:
            normalized_namespaces = [
                _normalize_namespace(item) for item in namespaces
            ]
            namespace_filter = "AND namespace = ANY(:namespaces)"
            params["namespaces"] = normalized_namespaces
        rows = session.exec(
            text(
                f"""
                SELECT id FROM user_memories
                WHERE user_id = :user_id
                  AND is_active = TRUE
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                  {namespace_filter}
                  AND to_tsvector(
                        'simple', coalesce(key, '') || ' ' || coalesce(content, '')
                      ) @@ plainto_tsquery('simple', :query)
                LIMIT 100
                """
            ),
            params=params,
        ).all()
        full_text_ids = [int(row[0]) for row in rows]
        if full_text_ids:
            full_text_memories = session.exec(
                select(UserMemory).where(UserMemory.id.in_(full_text_ids))
            ).all()
            candidates.update({memory.id: memory for memory in full_text_memories})

    return list(candidates.values())


def _fit_item_to_budget(
    item: dict[str, Any],
    char_budget: int,
    content_field: str,
) -> dict[str, Any]:
    content = str(item[content_field])
    low = 0
    high = len(content)
    best = {**item, content_field: "…"}
    while low <= high:
        middle = (low + high) // 2
        candidate = {**item, content_field: content[:middle] + "…"}
        serialized = json.dumps([candidate], ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= char_budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best
