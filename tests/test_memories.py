import unittest
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import (
    Conversation,
    MemoryConsolidationCursor,
    Message,
    User,
    UserMemoryDocument,
)
from services.account.memories import (
    MAX_MEMORY_DOCUMENT_CHARS,
    build_memory_context,
    clear_memory_document,
    get_memory_document,
    get_memory_settings,
    update_memory_document,
    update_memory_settings,
)


class MemoryDocumentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.user_id = 1_000_000_001
        with Session(self.engine) as session:
            session.add(
                User(
                    id=self.user_id,
                    platform="tg",
                    platform_user_id="42",
                    username="tester",
                )
            )
            session.commit()

        self.stack = ExitStack()
        self.stack.enter_context(
            patch("services.account.memories.get_engine", return_value=self.engine)
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_metadata_only_contains_markdown_memory_tables(self) -> None:
        memory_tables = sorted(
            table_name
            for table_name in SQLModel.metadata.tables
            if "memor" in table_name
        )
        self.assertEqual(
            memory_tables,
            [
                "memory_consolidation_cursors",
                "user_memory_document_settings",
                "user_memory_documents",
            ],
        )

    def test_get_memory_document_creates_one_empty_document_per_user(self) -> None:
        first = get_memory_document(self.user_id)
        second = get_memory_document(self.user_id)

        self.assertEqual(first.content, "")
        self.assertEqual(second.user_id, self.user_id)
        with Session(self.engine) as session:
            documents = session.exec(select(UserMemoryDocument)).all()
        self.assertEqual(len(documents), 1)

    def test_update_replaces_complete_markdown_and_builds_context(self) -> None:
        markdown = "# 用户记忆\n\n## 稳定偏好\n\n- 喜欢日常系动画"

        updated = update_memory_document(self.user_id, f"\n{markdown}\n")

        self.assertEqual(updated.content, markdown)
        self.assertEqual(build_memory_context(self.user_id), markdown)

    def test_clear_document_keeps_single_empty_record(self) -> None:
        update_memory_document(self.user_id, "# 用户记忆\n\n- 喜欢漫画")

        cleared = clear_memory_document(self.user_id)

        self.assertEqual(cleared.content, "")
        self.assertEqual(build_memory_context(self.user_id), "")
        with Session(self.engine) as session:
            documents = session.exec(select(UserMemoryDocument)).all()
        self.assertEqual(len(documents), 1)

    def test_document_rejects_content_over_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            update_memory_document(self.user_id, "记" * (MAX_MEMORY_DOCUMENT_CHARS + 1))

    def test_memory_settings_only_control_enable_and_auto_extract(self) -> None:
        defaults = get_memory_settings(self.user_id)
        updated = update_memory_settings(
            self.user_id,
            enabled=False,
            auto_extract=False,
        )

        self.assertTrue(defaults.enabled)
        self.assertTrue(defaults.auto_extract)
        self.assertFalse(updated.enabled)
        self.assertFalse(updated.auto_extract)

    def test_user_edit_advances_existing_conversation_cursor(self) -> None:
        with Session(self.engine) as session:
            conversation = Conversation(
                user_id=self.user_id,
                platform="tg",
                platform_user_id="42",
                thread_id="manual-memory-edit",
            )
            session.add(conversation)
            session.flush()
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="旧消息里的偏好",
                )
            )
            session.commit()
            conversation_id = conversation.id

        update_memory_document(self.user_id, "# 用户记忆\n\n- 用户人工整理结果")

        with Session(self.engine) as session:
            cursor = session.get(MemoryConsolidationCursor, conversation_id)
            latest_message_id = session.exec(
                select(Message.id).where(Message.conversation_id == conversation_id)
            ).one()
        self.assertEqual(cursor.source_message_id, latest_message_id)


if __name__ == "__main__":
    unittest.main()
