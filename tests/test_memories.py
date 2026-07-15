import unittest
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import (
    Conversation,
    ConversationMemory,
    MemoryRevision,
    User,
    UserMemory,
    utc_now,
)
from services.account.conversation_memories import upsert_conversation_memory
from services.account.memories import (
    build_memory_context,
    forget_all_memories,
    forget_memory,
    list_memories,
    remember_memory,
    retrieve_memories,
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
        self.stack.enter_context(
            patch(
                "services.account.conversation_memories.get_engine",
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
            revisions = session.exec(select(MemoryRevision)).all()

        self.assertEqual(len(memories), 1)
        self.assertTrue(memories[0].is_active)
        self.assertEqual([revision.action for revision in revisions], ["create", "update"])
        self.assertEqual(revisions[1].previous_content, "用户喜欢芳文社作品。")

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
            revisions = session.exec(select(MemoryRevision)).all()

        self.assertFalse(memory.is_active)
        self.assertEqual(revisions[-1].action, "forget")

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

        self.assertIn('"kind":"profile"', context)
        self.assertIn('"content":"用户希望被称呼为小鸽。"', context)
        self.assertIn('"kind":"dislike"', context)
        self.assertIn('"content":"用户不喜欢动画剧透。"', context)

    def test_retrieve_memories_uses_query_and_tracks_access(self) -> None:
        relevant = remember_memory(
            user_id=self.user_id,
            kind="preference",
            key="favorite studio",
            content="用户喜欢芳文社动画。",
            importance=0.7,
        ).memory
        remember_memory(
            user_id=self.user_id,
            kind="note",
            key="breakfast",
            content="用户今天早饭吃了面包。",
            importance=0.2,
        )

        memories = retrieve_memories(self.user_id, "推荐一部芳文社的新动画", limit=1)

        self.assertEqual([memory.id for memory in memories], [relevant.id])
        self.assertEqual(memories[0].access_count, 1)
        self.assertIsNotNone(memories[0].last_accessed_at)

    def test_expired_memory_is_not_retrieved(self) -> None:
        remember_memory(
            user_id=self.user_id,
            key="temporary plan",
            content="用户今天准备看电影。",
            expires_at=utc_now(),
        )

        self.assertEqual(retrieve_memories(self.user_id, "今天看什么电影"), [])

    def test_memory_context_respects_character_budget(self) -> None:
        remember_memory(
            user_id=self.user_id,
            key="long note",
            content="很长的记忆" * 200,
            importance=1.0,
        )

        context = build_memory_context(
            self.user_id,
            query="long note",
            char_budget=300,
        )

        self.assertLessEqual(len(context), 300)
        self.assertIn("…", context)

    def test_unknown_kind_falls_back_to_note(self) -> None:
        result = remember_memory(
            user_id=self.user_id,
            kind="random",
            key="memo",
            content="用户提到下次继续聊漫画。",
        )

        self.assertEqual(result.memory.kind, "note")

    def test_namespace_allows_same_key_and_limits_retrieval(self) -> None:
        remember_memory(
            user_id=self.user_id,
            namespace="global",
            kind="note",
            key="current project",
            content="全局项目。",
        )
        platform_memory = remember_memory(
            user_id=self.user_id,
            namespace="platform:tg",
            kind="note",
            key="current project",
            content="TG 平台项目。",
        ).memory

        retrieved = retrieve_memories(
            self.user_id,
            "current project",
            namespaces=["platform:tg"],
        )

        self.assertEqual([memory.id for memory in retrieved], [platform_memory.id])

    def test_memory_context_can_include_previous_episode(self) -> None:
        with Session(self.engine) as session:
            conversation = Conversation(
                user_id=self.user_id,
                platform="tg",
                platform_user_id="42",
                thread_id="episode-thread",
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)

        upsert_conversation_memory(
            conversation_id=conversation.id,
            user_id=self.user_id,
            namespace="platform:tg",
            title="漫画计划",
            summary="上次约定继续讨论漫画推荐。",
            topics=["漫画"],
            open_items=["继续推荐"],
            source_message_id=None,
        )

        context = build_memory_context(
            self.user_id,
            query="继续上次的漫画计划",
            namespaces=["global", "platform:tg"],
        )

        self.assertIn('"memory_type":"episode"', context)
        self.assertIn("上次约定继续讨论漫画推荐", context)

    def test_forget_all_memories_also_deactivates_episode_summaries(self) -> None:
        remember_memory(
            user_id=self.user_id,
            key="favorite genre",
            content="用户喜欢日常系动画。",
        )
        with Session(self.engine) as session:
            conversation = Conversation(
                user_id=self.user_id,
                platform="tg",
                platform_user_id="42",
                thread_id="clear-memory-thread",
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
        upsert_conversation_memory(
            conversation_id=conversation.id,
            user_id=self.user_id,
            namespace="platform:tg",
            title="动画偏好",
            summary="用户喜欢日常系动画。",
            topics=["动画"],
            open_items=[],
            source_message_id=None,
        )

        self.assertEqual(forget_all_memories(self.user_id), 2)
        self.assertEqual(build_memory_context(self.user_id, query="动画"), "")
        with Session(self.engine) as session:
            episode = session.exec(select(ConversationMemory)).one()
        self.assertFalse(episode.is_active)


if __name__ == "__main__":
    unittest.main()
