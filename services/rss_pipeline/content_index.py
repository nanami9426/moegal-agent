import hashlib
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlmodel import Session, delete, select

from db.models import ContentChunk, ContentItem, utc_now
from db.session import get_engine
from utils.llm import get_base_url


EMBEDDING_MODEL_ENV = "MOEGAL_EMBEDDING_MODEL"
EMBEDDING_BASE_URL_ENV = "MOEGAL_EMBEDDING_BASE_URL"
EMBEDDING_API_KEY_ENV = "MOEGAL_EMBEDDING_API_KEY"
EMBEDDING_DIMENSIONS_ENV = "MOEGAL_EMBEDDING_DIMENSIONS"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
CONTENT_CHUNK_SIZE = 1200
CONTENT_CHUNK_OVERLAP = 120
CONTENT_CHUNK_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class ContentIndexResult:
    indexed_items: int = 0
    indexed_chunks: int = 0
    unchanged_items: int = 0
    stale_items: int = 0
    disabled: bool = False


@dataclass(frozen=True)
class _TargetChunk:
    chunk_index: int
    text: str
    content_hash: str


def get_embedding_model_name() -> str | None:
    model = os.getenv(EMBEDDING_MODEL_ENV, "").strip()
    if not model:
        return None
    if len(model) > 128:
        raise ValueError(f"{EMBEDDING_MODEL_ENV} 不能超过 128 个字符。")
    return model


def get_embedding_dimensions() -> int | None:
    raw_value = os.getenv(EMBEDDING_DIMENSIONS_ENV, "").strip()
    if not raw_value:
        return None
    try:
        dimensions = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{EMBEDDING_DIMENSIONS_ENV} 必须是整数。") from exc
    if not 1 <= dimensions <= 16_000:
        raise ValueError(f"{EMBEDDING_DIMENSIONS_ENV} 必须在 1～16000 之间。")
    return dimensions


@lru_cache
def _build_embeddings(
    model: str,
    base_url: str | None,
    api_key: str,
    dimensions: int | None,
) -> Any:
    # 延迟导入，未启用 RAG 时不加载 Embedding 客户端及其网络资源。
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=model,
        api_key=api_key,
        base_url=base_url,
        dimensions=dimensions,
    )


def get_embedding_client(model: str) -> Any:
    api_key = (
        os.getenv(EMBEDDING_API_KEY_ENV)
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
    if not api_key:
        raise RuntimeError(
            f"Missing {EMBEDDING_API_KEY_ENV} or OPENAI_API_KEY. 请先在 .env 中配置。"
        )
    configured_base_url = os.getenv(EMBEDDING_BASE_URL_ENV, "").strip()
    base_url = configured_base_url or get_base_url()
    return _build_embeddings(model, base_url, api_key, get_embedding_dimensions())


def index_content_items(items: list[ContentItem]) -> ContentIndexResult:
    """按内容 hash 增量生成 RSS 分块向量，未配置模型时安全跳过。"""
    model = get_embedding_model_name()
    if model is None:
        return ContentIndexResult(disabled=True)
    configured_dimensions = get_embedding_dimensions()

    item_by_id = {
        item.id: item
        for item in items
        if item.id is not None and item.source_type == "rss"
    }
    if not item_by_id:
        return ContentIndexResult()

    with Session(get_engine()) as session:
        existing_chunks = session.exec(
            select(ContentChunk).where(
                ContentChunk.content_item_id.in_(list(item_by_id)),
            )
        ).all()

    existing_by_item: dict[int, list[ContentChunk]] = {}
    for chunk in existing_chunks:
        existing_by_item.setdefault(chunk.content_item_id, []).append(chunk)

    pending: dict[int, list[_TargetChunk]] = {}
    unchanged_items = 0
    for item_id, item in item_by_id.items():
        target_chunks = build_content_chunks(item)
        existing = sorted(
            existing_by_item.get(item_id, []),
            key=lambda chunk: chunk.chunk_index,
        )
        if _chunks_are_current(
            existing,
            target_chunks,
            model,
            configured_dimensions,
        ):
            unchanged_items += 1
            continue
        pending[item_id] = target_chunks

    texts = [chunk.text for chunks in pending.values() for chunk in chunks]
    if not texts:
        return ContentIndexResult(unchanged_items=unchanged_items)

    raw_vectors = get_embedding_client(model).embed_documents(
        texts,
        chunk_size=_embedding_batch_size(),
    )
    vectors = _validate_vectors(
        raw_vectors,
        expected_count=len(texts),
        expected_dimensions=configured_dimensions,
    )

    vectors_by_item: dict[int, list[list[float]]] = {}
    offset = 0
    for item_id, chunks in pending.items():
        vectors_by_item[item_id] = vectors[offset : offset + len(chunks)]
        offset += len(chunks)

    indexed_items = 0
    indexed_chunks = 0
    stale_items = 0
    now = utc_now()
    with Session(get_engine()) as session:
        for item_id, chunks in pending.items():
            current_item = session.get(ContentItem, item_id)
            expected_item = item_by_id[item_id]
            # Embedding 调用期间内容可能刷新；旧结果不能覆盖新版本。
            if current_item is None or current_item.hash != expected_item.hash:
                stale_items += 1
                continue

            session.exec(
                delete(ContentChunk).where(ContentChunk.content_item_id == item_id)
            )
            for chunk, vector in zip(chunks, vectors_by_item[item_id], strict=True):
                session.add(
                    ContentChunk(
                        content_item_id=item_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        content_hash=chunk.content_hash,
                        embedding_model=model,
                        embedding_dimensions=len(vector),
                        embedding=vector,
                        created_at=now,
                        updated_at=now,
                    )
                )
                indexed_chunks += 1
            indexed_items += 1
        session.commit()

    return ContentIndexResult(
        indexed_items=indexed_items,
        indexed_chunks=indexed_chunks,
        unchanged_items=unchanged_items,
        stale_items=stale_items,
    )


def index_cached_content(*, batch_size: int = 100) -> ContentIndexResult:
    """补建全部历史 RSS 缓存的向量；切换模型后也可安全重复执行。"""
    if get_embedding_model_name() is None:
        return ContentIndexResult(disabled=True)

    resolved_batch_size = max(1, min(batch_size, 500))
    last_item_id = 0
    total = ContentIndexResult()
    while True:
        with Session(get_engine()) as session:
            items = list(
                session.exec(
                    select(ContentItem)
                    .where(
                        ContentItem.source_type == "rss",
                        ContentItem.id > last_item_id,
                    )
                    .order_by(ContentItem.id)
                    .limit(resolved_batch_size)
                ).all()
            )
        if not items:
            return total

        result = index_content_items(items)
        total = ContentIndexResult(
            indexed_items=total.indexed_items + result.indexed_items,
            indexed_chunks=total.indexed_chunks + result.indexed_chunks,
            unchanged_items=total.unchanged_items + result.unchanged_items,
            stale_items=total.stale_items + result.stale_items,
            disabled=result.disabled,
        )
        last_item_id = max(item.id or last_item_id for item in items)


def build_content_chunks(item: ContentItem) -> list[_TargetChunk]:
    """RSS 通常较短；长摘要才按重叠窗口切分，标题和元数据保留在每块。"""
    metadata: list[str] = []
    if item.title:
        metadata.append(f"标题：{item.title.strip()}")
    if item.author:
        metadata.append(f"作者：{item.author.strip()}")
    tags = item.raw.get("tags") if isinstance(item.raw, dict) else None
    if isinstance(tags, list):
        clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if clean_tags:
            metadata.append("标签：" + "、".join(clean_tags))

    body = " ".join((item.summary or "").split())
    body_chunks = _split_text(body) if body else [""]
    prefix = "\n".join(metadata)
    chunks: list[_TargetChunk] = []
    for index, body_chunk in enumerate(body_chunks):
        parts = [prefix] if prefix else []
        if body_chunk:
            parts.append(f"内容：{body_chunk}")
        text = "\n".join(parts).strip()
        if not text:
            continue
        source_hash = item.hash or hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_hash = hashlib.sha256(
            f"{CONTENT_CHUNK_SCHEMA_VERSION}|{source_hash}|{index}|{text}".encode("utf-8")
        ).hexdigest()
        chunks.append(
            _TargetChunk(
                chunk_index=index,
                text=text,
                content_hash=chunk_hash,
            )
        )
    return chunks


def _split_text(text: str) -> list[str]:
    if len(text) <= CONTENT_CHUNK_SIZE:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CONTENT_CHUNK_SIZE)
        if end < len(text):
            # 优先在自然标点或空格处分块，避免截断句子。
            candidates = [
                text.rfind(separator, start + CONTENT_CHUNK_SIZE // 2, end)
                for separator in ("。", "！", "？", ". ", " ")
            ]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - CONTENT_CHUNK_OVERLAP)
    return [chunk for chunk in chunks if chunk]


def _chunks_are_current(
    existing: list[ContentChunk],
    targets: list[_TargetChunk],
    model: str,
    dimensions: int | None,
) -> bool:
    if len(existing) != len(targets):
        return False
    return all(
        stored.chunk_index == target.chunk_index
        and stored.content_hash == target.content_hash
        and stored.embedding_model == model
        and (dimensions is None or stored.embedding_dimensions == dimensions)
        for stored, target in zip(existing, targets, strict=True)
    )


def _validate_vectors(
    vectors: list[list[float]],
    *,
    expected_count: int,
    expected_dimensions: int | None = None,
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise ValueError(
            f"Embedding 返回 {len(vectors)} 条向量，预期 {expected_count} 条。"
        )

    normalized: list[list[float]] = []
    dimensions: int | None = None
    for vector in vectors:
        values = [float(value) for value in vector]
        if not values or not all(math.isfinite(value) for value in values):
            raise ValueError("Embedding 返回了空向量或非有限数值。")
        if dimensions is None:
            dimensions = len(values)
            if expected_dimensions is not None and dimensions != expected_dimensions:
                raise ValueError(
                    f"Embedding 返回 {dimensions} 维向量，预期 {expected_dimensions} 维。"
                )
        elif len(values) != dimensions:
            raise ValueError("同一批 Embedding 的向量维度不一致。")
        normalized.append(values)
    return normalized


def _embedding_batch_size() -> int:
    raw_value = os.getenv(
        "MOEGAL_EMBEDDING_BATCH_SIZE",
        str(DEFAULT_EMBEDDING_BATCH_SIZE),
    )
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_EMBEDDING_BATCH_SIZE
    return max(1, min(value, 256))
