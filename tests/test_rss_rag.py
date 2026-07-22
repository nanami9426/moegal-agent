import json
import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import ContentChunk
from services.rss_pipeline.content_index import (
    get_embedding_dimensions,
    index_cached_content,
    index_content_items,
)
from services.rss_pipeline.content_store import upsert_rss_entries
from services.rss_pipeline.feeds import RssEntry
from services.rss_pipeline.retrieval import (
    format_rss_search_results,
    search_rss_content,
)


class RssRagTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.embeddings = _FakeEmbeddings()
        self.stack = ExitStack()
        self.stack.enter_context(
            patch("services.rss_pipeline.content_store.get_engine", return_value=self.engine)
        )
        self.stack.enter_context(
            patch("services.rss_pipeline.content_index.get_engine", return_value=self.engine)
        )
        self.stack.enter_context(
            patch("services.rss_pipeline.retrieval.get_engine", return_value=self.engine)
        )
        self.stack.enter_context(
            patch(
                "services.rss_pipeline.content_index.get_embedding_client",
                return_value=self.embeddings,
            )
        )
        self.stack.enter_context(
            patch(
                "services.rss_pipeline.retrieval.get_embedding_client",
                return_value=self.embeddings,
            )
        )
        self.stack.enter_context(
            patch.dict(
                os.environ,
                {"MOEGAL_EMBEDDING_MODEL": "test-embedding"},
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_index_is_incremental_and_reindexes_changed_content(self) -> None:
        first_upsert = upsert_rss_entries(
            [self._entry("blue-archive", "蓝色档案 新活动", "学生们参加夏日活动")]
        )

        first = index_content_items(first_upsert.items)
        second = index_content_items(first_upsert.items)

        self.assertEqual(first.indexed_items, 1)
        self.assertEqual(first.indexed_chunks, 1)
        self.assertEqual(second.unchanged_items, 1)
        self.assertEqual(len(self.embeddings.document_calls), 1)

        changed_upsert = upsert_rss_entries(
            [self._entry("blue-archive", "蓝色档案 新活动", "追加了新的剧情章节")]
        )
        changed = index_content_items(changed_upsert.items)

        self.assertEqual(changed.indexed_items, 1)
        self.assertEqual(len(self.embeddings.document_calls), 2)
        with Session(self.engine) as session:
            chunks = session.exec(select(ContentChunk)).all()
        self.assertEqual(len(chunks), 1)
        self.assertIn("追加了新的剧情章节", chunks[0].text)

    def test_hybrid_search_finds_semantically_related_content(self) -> None:
        upsert = upsert_rss_entries(
            [
                self._entry(
                    "blue-archive",
                    "蓝色档案 新活动",
                    "学生们将在学园都市参加夏日活动",
                ),
                self._entry(
                    "music",
                    "孤独摇滚 新专辑",
                    "乐队公开了新曲目",
                ),
            ]
        )
        index_content_items(upsert.items)

        results = search_rss_content("校园战术游戏有什么动态", days=30, limit=2)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].title, "蓝色档案 新活动")
        self.assertIn("semantic", results[0].matched_by)

    def test_backfill_indexes_all_cached_content_and_is_repeatable(self) -> None:
        upsert_rss_entries(
            [
                self._entry("blue-archive", "蓝色档案 新活动", "学园都市夏日活动"),
                self._entry("music", "孤独摇滚 新专辑", "乐队公开新曲目"),
            ]
        )

        first = index_cached_content(batch_size=1)
        second = index_cached_content(batch_size=1)

        self.assertEqual(first.indexed_items, 2)
        self.assertEqual(first.indexed_chunks, 2)
        self.assertEqual(second.unchanged_items, 2)
        self.assertEqual(len(self.embeddings.document_calls), 2)

    def test_keyword_search_still_works_when_embedding_is_disabled(self) -> None:
        upsert_rss_entries(
            [self._entry("music", "孤独摇滚 新专辑", "乐队公开了新曲目")]
        )

        with patch.dict(os.environ, {"MOEGAL_EMBEDDING_MODEL": ""}):
            results = search_rss_content("孤独摇滚", days=30, limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "孤独摇滚 新专辑")
        self.assertEqual(results[0].matched_by, ("keyword",))

    def test_search_filters_old_content_and_formats_citations(self) -> None:
        upsert_rss_entries(
            [
                self._entry(
                    "recent",
                    "OpenAI 最新动态",
                    "本周发布了一项更新",
                ),
                self._entry(
                    "old",
                    "OpenAI 历史动态",
                    "很久以前的更新",
                    published_at=datetime.now(timezone.utc) - timedelta(days=90),
                ),
            ]
        )

        with patch.dict(os.environ, {"MOEGAL_EMBEDDING_MODEL": ""}):
            results = search_rss_content("OpenAI 动态", days=30, limit=5)
        formatted = format_rss_search_results(results)

        self.assertEqual([result.title for result in results], ["OpenAI 最新动态"])
        self.assertIn("[来源1]", formatted)
        self.assertIn("https://example.com/recent", formatted)
        self.assertIn("发布时间：", formatted)

    def test_evaluation_set_contains_30_distinct_questions(self) -> None:
        questions_path = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "rss_rag_questions.json"
        )
        questions = json.loads(questions_path.read_text(encoding="utf-8"))

        self.assertEqual(len(questions), 30)
        self.assertEqual(len({case["id"] for case in questions}), 30)
        self.assertTrue(all(case["query"].endswith(("？", "吗？")) for case in questions))

    def test_embedding_dimensions_are_validated(self) -> None:
        with patch.dict(os.environ, {"MOEGAL_EMBEDDING_DIMENSIONS": "1024"}):
            self.assertEqual(get_embedding_dimensions(), 1024)

        with patch.dict(os.environ, {"MOEGAL_EMBEDDING_DIMENSIONS": "invalid"}):
            with self.assertRaisesRegex(ValueError, "必须是整数"):
                get_embedding_dimensions()

    @staticmethod
    def _entry(
        entry_id: str,
        title: str,
        summary: str,
        *,
        published_at: datetime | None = None,
    ) -> RssEntry:
        return RssEntry(
            feed_url="https://example.com/feed.xml",
            feed_title="Example Feed",
            entry_id=entry_id,
            link=f"https://example.com/{entry_id}",
            title=title,
            summary=summary,
            author="Example Feed",
            published_at=published_at or datetime.now(timezone.utc),
            raw={
                "feed_url": "https://example.com/feed.xml",
                "feed_title": "Example Feed",
                "entry_id": entry_id,
                "link": f"https://example.com/{entry_id}",
                "tags": [],
            },
        )


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []

    def embed_documents(
        self,
        texts: list[str],
        *,
        chunk_size: int,
    ) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if "校园战术" in text:
            return [1.0, 0.0, 0.0]
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        if "蓝色档案" in text or "学园都市" in text:
            return [1.0, 0.0, 0.0]
        if "孤独摇滚" in text or "乐队" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


if __name__ == "__main__":
    unittest.main()
