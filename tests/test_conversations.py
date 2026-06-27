import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import Conversation, Message, User
from services.account.conversations import (
    append_message,
    get_or_create_active_conversation,
    start_new_conversation,
)


class ConversationServiceTest(unittest.TestCase):
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
            patch(
                "services.account.conversations.get_engine",
                return_value=self.engine,
            )
        )
        self.uuid_mock = self.stack.enter_context(
            patch(
                "services.account.conversations.uuid.uuid4",
                side_effect=[
                    uuid.UUID("00000000-0000-4000-8000-000000000001"),
                    uuid.UUID("00000000-0000-4000-8000-000000000002"),
                    uuid.UUID("00000000-0000-4000-8000-000000000003"),
                    uuid.UUID("00000000-0000-4000-8000-000000000004"),
                ],
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_get_or_create_active_conversation_reuses_v0(self) -> None:
        first = get_or_create_active_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )
        second = get_or_create_active_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.thread_id, "00000000-0000-4000-8000-000000000001")
        self.assertEqual(second.thread_id, first.thread_id)
        self.assertEqual(first.version, 0)
        self.assertEqual(second.version, 0)

        with Session(self.engine) as session:
            conversations = session.exec(select(Conversation)).all()
            self.assertEqual(len(conversations), 1)

    def test_start_new_conversation_deactivates_previous_version(self) -> None:
        old = get_or_create_active_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )
        append_message(
            conversation_id=old.id,
            role="user",
            content="你好",
        )
        result = start_new_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )
        new = result.context

        self.assertTrue(result.created)
        self.assertIsNotNone(new)
        self.assertEqual(old.thread_id, "00000000-0000-4000-8000-000000000001")
        self.assertEqual(new.thread_id, "00000000-0000-4000-8000-000000000002")
        self.assertEqual(old.version, 0)
        self.assertEqual(new.version, 1)

        with Session(self.engine) as session:
            old_row = session.get(Conversation, old.id)
            new_row = session.get(Conversation, new.id)

        self.assertIsNotNone(old_row)
        self.assertIsNotNone(new_row)
        self.assertFalse(old_row.is_active)
        self.assertIsNotNone(old_row.ended_at)
        self.assertTrue(new_row.is_active)

    def test_start_new_conversation_does_not_create_empty_first_record(self) -> None:
        result = start_new_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )

        self.assertFalse(result.created)
        self.assertIsNone(result.context)
        with Session(self.engine) as session:
            conversations = session.exec(select(Conversation)).all()
        self.assertEqual(conversations, [])

    def test_start_new_conversation_reuses_empty_active_conversation(self) -> None:
        active = get_or_create_active_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )

        result = start_new_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )

        self.assertFalse(result.created)
        self.assertIsNotNone(result.context)
        self.assertEqual(result.context.id, active.id)
        self.assertEqual(result.context.thread_id, active.thread_id)
        with Session(self.engine) as session:
            conversations = session.exec(select(Conversation)).all()
        self.assertEqual(len(conversations), 1)
        self.assertTrue(conversations[0].is_active)

    def test_append_message_stores_chat_log(self) -> None:
        conversation = get_or_create_active_conversation(
            user_id=self.user_id,
            platform="tg",
            platform_user_id="42",
        )
        append_message(
            conversation_id=conversation.id,
            role="user",
            content="你好",
            metadata_json={"thread_id": conversation.thread_id},
        )
        append_message(
            conversation_id=conversation.id,
            role="assistant",
            content="你好呀",
        )

        with Session(self.engine) as session:
            messages = session.exec(select(Message).order_by(Message.id)).all()

        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0].content, "你好")
        self.assertEqual(
            messages[0].metadata_json["thread_id"],
            "00000000-0000-4000-8000-000000000001",
        )


if __name__ == "__main__":
    unittest.main()
