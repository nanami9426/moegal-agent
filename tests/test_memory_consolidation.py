import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import Conversation, ConversationMemory, MemoryRevision, Message, User, UserMemory
from services.account.memory_consolidation import (
    ConsolidatedMemoryCandidate,
    ConsolidationOutput,
    consolidate_conversation,
)


class MemoryConsolidationTest(unittest.IsolatedAsyncioTestCase):
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
                )
            )
            conversation = Conversation(
                user_id=self.user_id,
                platform="tg",
                platform_user_id="42",
                thread_id="thread-1",
            )
            session.add(conversation)
            session.flush()
            self.conversation_id = conversation.id
            for index in range(6):
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content=f"第 {index} 轮：我喜欢日常系动画。",
                    )
                )
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="知道了。",
                    )
                )
            session.commit()

        self.stack = ExitStack()
        for target in (
            "services.account.memories.get_engine",
            "services.account.conversation_memories.get_engine",
            "services.account.memory_consolidation.get_engine",
        ):
            self.stack.enter_context(patch(target, return_value=self.engine))
        self.stack.enter_context(
            patch(
                "services.account.memory_consolidation.llm_user_headers",
                return_value={"x-user-id": str(self.user_id)},
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    async def test_consolidation_writes_episode_and_stable_memories(self) -> None:
        output = ConsolidationOutput(
            title="动画偏好",
            summary=(
                "用户多次确认喜欢日常系动画，后续可以继续推荐。"
                "用户声称 password is hunter2。"
            ),
            topics=["日常系动画", "邮箱 user@example.com"],
            open_items=["下次继续推荐", "记住手机号 13800138000"],
            memories=[
                ConsolidatedMemoryCandidate(
                    action="upsert",
                    kind="preference",
                    key="preference.anime.genre",
                    content="用户喜欢日常系动画。",
                    confidence=0.95,
                    importance=0.8,
                    reason="用户重复明确表达",
                ),
                ConsolidatedMemoryCandidate(
                    action="upsert",
                    kind="note",
                    key="profile.api_token",
                    content="用户的 token 是 sk-secret-secret-secret。",
                    confidence=1,
                    importance=1,
                ),
            ],
        )
        # OpenAI 兼容接口只需返回普通文本，不依赖 response_format。
        model = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=AIMessage(
                    content=f"```json\n{output.model_dump_json()}\n```",
                )
            )
        )
        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=model,
        ):
            result = await consolidate_conversation(self.conversation_id)

        self.assertFalse(result.skipped)
        self.assertEqual(result.processed_messages, 12)
        self.assertEqual(result.upserted_memories, 1)
        model.ainvoke.assert_awaited_once()
        self.assertEqual(
            model.ainvoke.await_args.kwargs["extra_headers"],
            {"x-user-id": str(self.user_id)},
        )
        request_messages = model.ainvoke.await_args.args[0]
        self.assertIsInstance(request_messages[0], SystemMessage)
        self.assertIn("JSON schema", request_messages[0].content)

        with Session(self.engine) as session:
            episode = session.exec(select(ConversationMemory)).one()
            memories = session.exec(select(UserMemory)).all()
            revisions = session.exec(select(MemoryRevision)).all()

        self.assertEqual(episode.namespace, "platform:tg")
        self.assertEqual(episode.title, "动画偏好")
        self.assertEqual(episode.open_items, ["下次继续推荐"])
        self.assertEqual(episode.topics, ["日常系动画"])
        self.assertNotIn("hunter2", episode.summary)
        self.assertIn("日常系动画", episode.summary)
        self.assertIsNotNone(episode.source_message_id)
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].key, "preference.anime.genre")
        self.assertEqual(memories[0].source, "summary")
        self.assertEqual(memories[0].confidence, 0.9)
        self.assertEqual(revisions[0].action, "create")

        with Session(self.engine) as session:
            session.add(
                Message(
                    conversation_id=self.conversation_id,
                    role="user",
                    content="更正一下，我现在更喜欢治愈系动画。",
                )
            )
            session.add(
                Message(
                    conversation_id=self.conversation_id,
                    role="assistant",
                    content="已更正。",
                )
            )
            session.commit()

        corrected_output = ConsolidationOutput(
            title="动画偏好更新",
            summary="用户把偏好更正为治愈系动画。",
            topics=["治愈系动画"],
            memories=[
                ConsolidatedMemoryCandidate(
                    action="upsert",
                    kind="preference",
                    key="preference.anime.genre",
                    content="用户现在更喜欢治愈系动画。",
                    confidence=0.9,
                    importance=0.8,
                    reason="用户明确更正",
                )
            ],
        )
        corrected_model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=corrected_output)
        )
        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=corrected_model,
        ):
            corrected = await consolidate_conversation(
                self.conversation_id,
                force=True,
            )

        self.assertEqual(corrected.processed_messages, 2)
        with Session(self.engine) as session:
            memories = session.exec(select(UserMemory)).all()
            revisions = session.exec(select(MemoryRevision).order_by(MemoryRevision.id)).all()
            episode = session.exec(select(ConversationMemory)).one()
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].content, "用户现在更喜欢治愈系动画。")
        self.assertEqual([revision.action for revision in revisions], ["create", "update"])
        self.assertEqual(episode.title, "动画偏好更新")

    async def test_consolidation_skips_when_threshold_not_reached(self) -> None:
        with Session(self.engine) as session:
            messages = session.exec(
                select(Message).where(Message.conversation_id == self.conversation_id)
            ).all()
            for message in messages[2:]:
                session.delete(message)
            session.commit()

        model = SimpleNamespace(ainvoke=AsyncMock())
        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=model,
        ):
            result = await consolidate_conversation(self.conversation_id)

        self.assertTrue(result.skipped)
        model.ainvoke.assert_not_awaited()

    async def test_plain_completion_request_has_no_response_format(self) -> None:
        captured_request: dict[str, object] = {}
        output = ConsolidationOutput(
            title="本地协议测试",
            summary="验证普通 JSON 响应可以被解析。",
        )

        async def handle_request(request: httpx.Request) -> httpx.Response:
            captured_request.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-memory-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": output.model_dump_json(),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        model = ChatOpenAI(
            model="test-model",
            api_key="test-key",
            base_url="https://memory.test/v1",
            temperature=0,
            http_async_client=async_client,
        )
        try:
            with patch(
                "services.account.memory_consolidation._get_consolidation_model",
                return_value=model,
            ):
                result = await consolidate_conversation(self.conversation_id)
        finally:
            await async_client.aclose()

        self.assertFalse(result.skipped)
        self.assertNotIn("response_format", captured_request)
        self.assertEqual(captured_request["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
