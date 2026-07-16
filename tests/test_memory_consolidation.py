import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
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
from services.account.memories import update_memory_document, update_memory_settings
from services.account.memory_consolidation import (
    CONSOLIDATION_SYSTEM_PROMPT,
    MemoryDocumentChangedError,
    consolidate_conversation,
)


class MemoryConsolidationTest(unittest.IsolatedAsyncioTestCase):
    def test_consolidation_prompt_excludes_subscription_data(self) -> None:
        self.assertIn("不保存订阅或取消订阅的关键词", CONSOLIDATION_SYSTEM_PROMPT)
        self.assertIn("删除旧文档中已有的此类内容", CONSOLIDATION_SYSTEM_PROMPT)
        self.assertIn("不得仅因用户订阅某关键词就推断用户长期偏好", CONSOLIDATION_SYSTEM_PROMPT)

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

    async def test_consolidation_replaces_markdown_and_advances_cursor(self) -> None:
        first_markdown = """```markdown
# 用户记忆

## 稳定偏好
- 喜欢日常系动画
- 邮箱 user@example.com
```"""
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=first_markdown)))
        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=model,
        ):
            result = await consolidate_conversation(self.conversation_id)

        self.assertFalse(result.skipped)
        self.assertTrue(result.document_updated)
        self.assertEqual(result.processed_messages, 12)
        self.assertEqual(
            model.ainvoke.await_args.kwargs["extra_headers"],
            {"x-user-id": str(self.user_id)},
        )
        request_payload = json.loads(model.ainvoke.await_args.args[0][1].content)
        self.assertEqual(request_payload["old_memory_markdown"], "")
        self.assertEqual(len(request_payload["new_messages"]), 12)

        with Session(self.engine) as session:
            document = session.get(UserMemoryDocument, self.user_id)
            cursor = session.get(MemoryConsolidationCursor, self.conversation_id)
        self.assertIn("喜欢日常系动画", document.content)
        self.assertNotIn("user@example.com", document.content)
        self.assertIsNotNone(cursor.source_message_id)

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
                    content="明白。",
                )
            )
            session.commit()

        second_markdown = "# 用户记忆\n\n## 稳定偏好\n- 喜欢治愈系动画"
        corrected_model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content=second_markdown))
        )
        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=corrected_model,
        ):
            corrected = await consolidate_conversation(self.conversation_id, force=True)

        self.assertEqual(corrected.processed_messages, 2)
        second_payload = json.loads(corrected_model.ainvoke.await_args.args[0][1].content)
        self.assertIn("喜欢日常系动画", second_payload["old_memory_markdown"])
        with Session(self.engine) as session:
            documents = session.exec(select(UserMemoryDocument)).all()
        self.assertEqual(len(documents), 1)
        self.assertIn("喜欢治愈系动画", documents[0].content)
        self.assertNotIn("喜欢日常系动画", documents[0].content)

    async def test_consolidation_skips_below_threshold(self) -> None:
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

    async def test_consolidation_respects_disabled_auto_extract(self) -> None:
        update_memory_settings(self.user_id, auto_extract=False)
        model = SimpleNamespace(ainvoke=AsyncMock())

        with patch(
            "services.account.memory_consolidation._get_consolidation_model",
            return_value=model,
        ):
            result = await consolidate_conversation(self.conversation_id)

        self.assertTrue(result.skipped)
        model.ainvoke.assert_not_awaited()

    async def test_user_edit_during_model_call_is_not_overwritten(self) -> None:
        with Session(self.engine) as session:
            session.add(
                UserMemoryDocument(
                    user_id=self.user_id,
                    content="# 用户记忆\n\n- 原始内容",
                )
            )
            session.commit()

        async def edit_then_reply(*args: object, **kwargs: object) -> AIMessage:
            update_memory_document(self.user_id, "# 用户记忆\n\n- 用户手动编辑")
            return AIMessage(content="# 用户记忆\n\n- 后台旧结果")

        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=edit_then_reply))
        with (
            patch(
                "services.account.memory_consolidation._get_consolidation_model",
                return_value=model,
            ),
            self.assertRaises(MemoryDocumentChangedError),
        ):
            await consolidate_conversation(self.conversation_id)

        with Session(self.engine) as session:
            document = session.get(UserMemoryDocument, self.user_id)
            cursor = session.get(MemoryConsolidationCursor, self.conversation_id)
        self.assertIn("用户手动编辑", document.content)
        self.assertIsNotNone(cursor.source_message_id)

    async def test_plain_completion_request_has_no_response_format(self) -> None:
        captured_request: dict[str, object] = {}

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
                                "content": "# 用户记忆\n\n- 本地协议测试",
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
