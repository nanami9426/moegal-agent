import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent import router


class RouterContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_route_message_uses_conversation_thread_id(self) -> None:
        graph = SimpleNamespace(
            ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
        )
        first_thread_id = "00000000-0000-4000-8000-000000000001"
        second_thread_id = "00000000-0000-4000-8000-000000000002"

        with (
            patch.object(router, "upsert_user", return_value=SimpleNamespace(id=1001)),
            patch.object(
                router,
                "get_or_create_active_conversation",
                side_effect=[
                    SimpleNamespace(id=1, thread_id=first_thread_id),
                    SimpleNamespace(id=2, thread_id=second_thread_id),
                ],
            ),
            patch.object(
                router,
                "start_new_conversation",
                return_value=SimpleNamespace(
                    context=SimpleNamespace(id=2, thread_id=second_thread_id),
                    created=True,
                ),
            ),
            patch.object(router, "append_message"),
            patch.object(router, "get_chat_graph", AsyncMock(return_value=graph)),
        ):
            first = await router.route_message("tg", "42", "你好")
            new_result = router.start_new_conversation_context("tg", "42")
            second = await router.route_message("tg", "42", "继续")

        self.assertEqual(first, "ok")
        self.assertEqual(second, "ok")
        self.assertTrue(new_result.created)
        self.assertEqual(new_result.context.thread_id, second_thread_id)
        self.assertEqual(
            graph.ainvoke.await_args_list[0].kwargs["config"],
            {"configurable": {"thread_id": first_thread_id}},
        )
        self.assertEqual(
            graph.ainvoke.await_args_list[1].kwargs["config"],
            {"configurable": {"thread_id": second_thread_id}},
        )

    async def test_conversation_thread_ids_are_scoped_per_user(self) -> None:
        graph = SimpleNamespace(
            ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
        )
        thread_ids: dict[str, str] = {}

        def start_new_conversation_side_effect(**kwargs):
            platform_user_id = kwargs["platform_user_id"]
            thread_ids[platform_user_id] = (
                "00000000-0000-4000-8000-000000000101"
            )
            return SimpleNamespace(
                context=SimpleNamespace(
                    id=10,
                    thread_id=thread_ids[platform_user_id],
                ),
                created=True,
            )

        def get_conversation_side_effect(**kwargs):
            platform_user_id = kwargs["platform_user_id"]
            thread_id = thread_ids.get(
                platform_user_id,
                "00000000-0000-4000-8000-000000000099",
            )
            return SimpleNamespace(
                id=20,
                thread_id=thread_id,
            )

        with (
            patch.object(router, "upsert_user", return_value=SimpleNamespace(id=1001)),
            patch.object(
                router,
                "start_new_conversation",
                side_effect=start_new_conversation_side_effect,
            ),
            patch.object(
                router,
                "get_or_create_active_conversation",
                side_effect=get_conversation_side_effect,
            ),
            patch.object(router, "append_message"),
            patch.object(router, "get_chat_graph", AsyncMock(return_value=graph)),
        ):
            router.start_new_conversation_context("tg", "42")
            await router.route_message("tg", "42", "你好")
            await router.route_message("tg", "99", "你好")

        self.assertEqual(
            graph.ainvoke.await_args_list[0].kwargs["config"],
            {"configurable": {"thread_id": "00000000-0000-4000-8000-000000000101"}},
        )
        self.assertEqual(
            graph.ainvoke.await_args_list[1].kwargs["config"],
            {"configurable": {"thread_id": "00000000-0000-4000-8000-000000000099"}},
        )

    async def test_route_image_message_builds_multimodal_message(self) -> None:
        image_bytes = b"image-bytes"
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="图片回答")))

        with patch.object(router, "_get_image_model", return_value=model):
            result = await router.route_image_message(
                "tg",
                "42",
                image_bytes,
                prompt="这是什么？",
            )

        self.assertEqual(result, "图片回答")
        model.ainvoke.assert_awaited_once()
        messages = model.ainvoke.await_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIsInstance(messages[1], HumanMessage)
        self.assertEqual(messages[1].content[0], {"type": "text", "text": "这是什么？"})
        self.assertEqual(
            messages[1].content[1],
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,"
                    + base64.b64encode(image_bytes).decode("utf8")
                },
            },
        )

    async def test_route_image_message_rejects_empty_image_without_model_call(self) -> None:
        with patch.object(router, "_get_image_model") as get_model_mock:
            result = await router.route_image_message("tg", "42", b"")

        self.assertEqual(result, "图片为空，无法识别。")
        get_model_mock.assert_not_called()

    def test_image_model_prefers_gateway_base_url(self) -> None:
        router._get_image_model.cache_clear()
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-key",
                    "MOEGAL_MODEL": "test-model",
                    "OPENAI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "MOEGAL_LLM_GATEWAY_BASE_URL": "http://127.0.0.1:9426/v1",
                },
            ),
            patch.object(router, "ChatOpenAI", return_value=SimpleNamespace()) as chat_openai,
        ):
            router._get_image_model()

        router._get_image_model.cache_clear()
        chat_openai.assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="http://127.0.0.1:9426/v1",
            temperature=0.6,
        )

    async def test_classify_image_translation_intent_uses_llm_label(self) -> None:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="skip")))

        with patch.object(router, "_get_intent_model", return_value=model):
            result = await router.classify_image_translation_intent("不用翻译了啊")

        self.assertEqual(result, "skip")
        model.ainvoke.assert_awaited_once()
        messages = model.ainvoke.await_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIsInstance(messages[1], HumanMessage)
        self.assertEqual(messages[1].content, "不用翻译了啊")

    async def test_classify_image_translation_intent_returns_unknown_for_bad_label(self) -> None:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="maybe")))

        with patch.object(router, "_get_intent_model", return_value=model):
            result = await router.classify_image_translation_intent("等一下")

        self.assertEqual(result, "unknown")


if __name__ == "__main__":
    unittest.main()
