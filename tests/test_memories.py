import unittest
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import User, UserMemory
from services.account.memories import (
    build_memory_context,
    forget_memory,
    list_memories,
    remember_memory,
)


class MemoryServiceTest(unittest.TestCase):
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
                "services.account.memories.get_engine",
                return_value=self.engine,
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_remember_memory_creates_and_updates_same_key(self) -> None:
        created = remember_memory(
            user_id=self.user_id,
            kind="preference",
            key=" Favorite Studio ",
            content="用户喜欢芳文社作品。",
        )
        updated = remember_memory(
            user_id=self.user_id,
            kind="preference",
            key="favorite studio",
            content="用户特别喜欢芳文社日常系作品。",
        )

        self.assertTrue(created.created)
        self.assertEqual(created.memory.key, "favorite studio")
        self.assertFalse(updated.created)
        self.assertEqual(updated.memory.content, "用户特别喜欢芳文社日常系作品。")

        with Session(self.engine) as session:
            memories = session.exec(select(UserMemory)).all()

        self.assertEqual(len(memories), 1)
        self.assertTrue(memories[0].is_active)

    def test_forget_memory_deactivates_matching_memory(self) -> None:
        remember_memory(
            user_id=self.user_id,
            kind="preference",
            key="favorite studio",
            content="用户喜欢芳文社作品。",
        )

        forgotten_count = forget_memory(
            user_id=self.user_id,
            kind="preference",
            key="favorite studio",
        )

        self.assertEqual(forgotten_count, 1)
        self.assertEqual(list_memories(self.user_id), [])
        self.assertEqual(build_memory_context(self.user_id), "")

        with Session(self.engine) as session:
            memory = session.exec(select(UserMemory)).one()

        self.assertFalse(memory.is_active)

    def test_build_memory_context_formats_active_memories(self) -> None:
        remember_memory(
            user_id=self.user_id,
            kind="profile",
            key="nickname",
            content="用户希望被称呼为小鸽。",
        )
        remember_memory(
            user_id=self.user_id,
            kind="dislike",
            key="spoiler",
            content="用户不喜欢动画剧透。",
        )

        context = build_memory_context(self.user_id)

        self.assertIn("kind=profile; key=nickname; content=用户希望被称呼为小鸽。", context)
        self.assertIn("kind=dislike; key=spoiler; content=用户不喜欢动画剧透。", context)

    def test_unknown_kind_falls_back_to_note(self) -> None:
        result = remember_memory(
            user_id=self.user_id,
            kind="random",
            key="memo",
            content="用户提到下次继续聊漫画。",
        )

        self.assertEqual(result.memory.kind, "note")


if __name__ == "__main__":
    unittest.main()
