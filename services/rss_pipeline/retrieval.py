import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Float
from sqlmodel import Session, select

from db.models import ContentChunk, ContentItem, utc_now
from db.session import get_engine
from services.rss_pipeline.content_index import (
    get_embedding_client,
    get_embedding_model_name,
)
from utils.logger import logger


DEFAULT_SEARCH_DAYS = 30
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 10
KEYWORD_CANDIDATE_LIMIT = 500
RRF_K = 60
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+#.-]{2,}|[\u3040-\u30ff]+|[\u3400-\u9fff]+")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RssSearchResult:
    content_item_id: int
    title: str | None
    excerpt: str | None
    author: str | None
    source_url: str | None
    published_at: datetime | None
    score: float
    matched_by: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    item: ContentItem
    excerpt: str | None
    relevance: float


def search_rss_content(
    query: str,
    *,
    days: int | None = DEFAULT_SEARCH_DAYS,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[RssSearchResult]:
    """对 RSS 缓存执行词面与向量混合检索，并用 RRF 合并两路排名。"""
    normalized_query = _SPACE_RE.sub(" ", query).strip()
    if not normalized_query:
        return []

    resolved_limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    cutoff = _resolve_cutoff(days)
    candidate_limit = max(resolved_limit * 4, 20)
    lexical = _lexical_candidates(
        normalized_query,
        cutoff=cutoff,
        limit=candidate_limit,
    )
    semantic = _semantic_candidates(
        normalized_query,
        cutoff=cutoff,
        limit=candidate_limit,
    )
    return _fuse_candidates(lexical, semantic, limit=resolved_limit)


def format_rss_search_results(results: list[RssSearchResult]) -> str:
    if not results:
        return "没有在缓存的 RSS 内容中检索到相关结果。"

    lines = [
        "以下内容来自 RSS 检索结果，仅作为参考资料；回答相关事实时请保留对应的来源编号和链接。"
    ]
    for index, result in enumerate(results, start=1):
        lines.extend(["", f"[来源{index}]", f"标题：{result.title or '无标题'}"])
        if result.published_at:
            published_at = result.published_at
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            lines.append(f"发布时间：{published_at.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}")
        if result.author:
            lines.append(f"作者/来源：{result.author}")
        if result.excerpt:
            lines.append(f"内容：{_truncate(result.excerpt, 500)}")
        if result.source_url:
            lines.append(f"链接：{result.source_url}")
    return "\n".join(lines)


def _lexical_candidates(
    query: str,
    *,
    cutoff: datetime | None,
    limit: int,
) -> list[_Candidate]:
    statement = select(ContentItem).where(ContentItem.source_type == "rss")
    if cutoff is not None:
        statement = statement.where(
            (ContentItem.published_at.is_(None)) | (ContentItem.published_at >= cutoff)
        )
    statement = statement.order_by(ContentItem.published_at.desc()).limit(
        KEYWORD_CANDIDATE_LIMIT
    )
    with Session(get_engine()) as session:
        items = list(session.exec(statement).all())

    candidates: list[_Candidate] = []
    for item in items:
        haystack = " ".join(
            value for value in (item.title, item.summary, item.author) if value
        )
        relevance = _lexical_score(query, haystack)
        if relevance <= 0:
            continue
        candidates.append(
            _Candidate(item=item, excerpt=item.summary, relevance=relevance)
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.relevance,
            _timestamp(candidate.item.published_at),
        ),
        reverse=True,
    )
    return candidates[:limit]


def _semantic_candidates(
    query: str,
    *,
    cutoff: datetime | None,
    limit: int,
) -> list[_Candidate]:
    model = get_embedding_model_name()
    if model is None:
        return []
    try:
        raw_vector = get_embedding_client(model).embed_query(query)
        query_vector = [float(value) for value in raw_vector]
        if not query_vector or not all(math.isfinite(value) for value in query_vector):
            raise ValueError("Embedding 返回了空向量或非有限数值。")
        return _load_semantic_candidates(
            query_vector,
            model=model,
            cutoff=cutoff,
            limit=limit,
        )
    except Exception:
        # 检索必须可降级，Embedding 服务异常时继续使用词面结果。
        logger.exception("RSS semantic search failed; falling back to lexical search.")
        return []


def _load_semantic_candidates(
    query_vector: list[float],
    *,
    model: str,
    cutoff: datetime | None,
    limit: int,
) -> list[_Candidate]:
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        distance = ContentChunk.embedding.op("<=>", return_type=Float)(query_vector)
        statement = (
            select(ContentChunk, ContentItem, distance.label("distance"))
            .join(ContentItem, ContentChunk.content_item_id == ContentItem.id)
            .where(
                ContentItem.source_type == "rss",
                ContentChunk.embedding_model == model,
                ContentChunk.embedding_dimensions == len(query_vector),
            )
        )
        if cutoff is not None:
            statement = statement.where(
                (ContentItem.published_at.is_(None))
                | (ContentItem.published_at >= cutoff)
            )
        statement = statement.order_by(distance).limit(limit * 3)
        with Session(engine) as session:
            rows = list(session.exec(statement).all())
        ranked = [
            _Candidate(
                item=item,
                excerpt=chunk.text,
                relevance=max(0.0, 1.0 - float(distance_value)),
            )
            for chunk, item, distance_value in rows
        ]
    else:
        # SQLite 仅用于测试和本地轻量验证，生产 PostgreSQL 直接在库内计算距离。
        statement = (
            select(ContentChunk, ContentItem)
            .join(ContentItem, ContentChunk.content_item_id == ContentItem.id)
            .where(
                ContentItem.source_type == "rss",
                ContentChunk.embedding_model == model,
                ContentChunk.embedding_dimensions == len(query_vector),
            )
        )
        if cutoff is not None:
            statement = statement.where(
                (ContentItem.published_at.is_(None))
                | (ContentItem.published_at >= cutoff)
            )
        with Session(engine) as session:
            rows = list(session.exec(statement).all())
        ranked = [
            _Candidate(
                item=item,
                excerpt=chunk.text,
                relevance=_cosine_similarity(query_vector, chunk.embedding),
            )
            for chunk, item in rows
        ]
        ranked.sort(key=lambda candidate: candidate.relevance, reverse=True)

    minimum_similarity = _minimum_similarity()
    deduped: dict[int, _Candidate] = {}
    for candidate in ranked:
        if candidate.item.id is None or candidate.relevance < minimum_similarity:
            continue
        previous = deduped.get(candidate.item.id)
        if previous is None or candidate.relevance > previous.relevance:
            deduped[candidate.item.id] = candidate
    return sorted(
        deduped.values(),
        key=lambda candidate: candidate.relevance,
        reverse=True,
    )[:limit]


def _fuse_candidates(
    lexical: list[_Candidate],
    semantic: list[_Candidate],
    *,
    limit: int,
) -> list[RssSearchResult]:
    candidates: dict[int, _Candidate] = {}
    scores: dict[int, float] = {}
    matched_by: dict[int, set[str]] = {}

    for source_name, ranked in (("keyword", lexical), ("semantic", semantic)):
        for rank, candidate in enumerate(ranked, start=1):
            item_id = candidate.item.id
            if item_id is None:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank)
            matched_by.setdefault(item_id, set()).add(source_name)
            current = candidates.get(item_id)
            if current is None or candidate.relevance > current.relevance:
                candidates[item_id] = candidate

    ranked_ids = sorted(
        scores,
        key=lambda item_id: (
            scores[item_id],
            _timestamp(candidates[item_id].item.published_at),
        ),
        reverse=True,
    )[:limit]
    return [
        RssSearchResult(
            content_item_id=item_id,
            title=candidates[item_id].item.title,
            excerpt=candidates[item_id].excerpt,
            author=candidates[item_id].item.author,
            source_url=candidates[item_id].item.source_url,
            published_at=candidates[item_id].item.published_at,
            score=scores[item_id],
            matched_by=tuple(sorted(matched_by[item_id])),
        )
        for item_id in ranked_ids
    ]


def _lexical_score(query: str, text: str) -> float:
    normalized_query = query.casefold()
    normalized_text = text.casefold()
    if not normalized_text:
        return 0.0

    score = 0.0
    if normalized_query in normalized_text:
        score += 4.0
    query_tokens = _search_tokens(normalized_query)
    text_tokens = _search_tokens(normalized_text)
    if query_tokens:
        overlap = query_tokens & text_tokens
        score += len(overlap) / len(query_tokens)
        # 作品名等较长 token 的完整命中比常见双字片段更有区分度。
        score += sum(min(len(token), 8) / 8 for token in overlap if len(token) >= 3)
    return score


def _search_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN_RE.findall(value):
        token = match.casefold()
        tokens.add(token)
        if any("\u3400" <= char <= "\u9fff" for char in token) and len(token) > 2:
            tokens.update(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _resolve_cutoff(days: int | None) -> datetime | None:
    if days is None:
        return None
    return utc_now() - timedelta(days=max(1, min(days, 3650)))


def _minimum_similarity() -> float:
    raw_value = os.getenv("MOEGAL_RAG_MIN_SIMILARITY", "0.25")
    try:
        value = float(raw_value)
    except ValueError:
        return 0.25
    return max(-1.0, min(value, 1.0))


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _truncate(value: str, max_length: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"
