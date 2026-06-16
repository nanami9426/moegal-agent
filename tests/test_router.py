import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent import router


class RouterContextTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with router._context_versions_lock:
            router._context_versions.clear()

    async def test_route_message_uses_versioned_thread_id(self) -> None:
        graph = SimpleNamespace(
            ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
        )

        with patch.object(router, "chat_graph", graph):
            first = await router.route_message("tg", "42", "你好")
            new_thread_id = router.start_new_conversation_context("tg", "42")
            second = await router.route_message("tg", "42", "继续")

        self.assertEqual(first, "ok")
        self.assertEqual(second, "ok")
        self.assertEqual(new_thread_id, "tg:42:v1")
        self.assertEqual(
            graph.ainvoke.await_args_list[0].kwargs["config"],
            {"configurable": {"thread_id": "tg:42:v0"}},
        )
        self.assertEqual(
            graph.ainvoke.await_args_list[1].kwargs["config"],
            {"configurable": {"thread_id": "tg:42:v1"}},
        )

    async def test_context_versions_are_scoped_per_user(self) -> None:
        graph = SimpleNamespace(
            ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
        )

        with patch.object(router, "chat_graph", graph):
            router.start_new_conversation_context("tg", "42")
            await router.route_message("tg", "42", "你好")
            await router.route_message("tg", "99", "你好")

        self.assertEqual(
            graph.ainvoke.await_args_list[0].kwargs["config"],
            {"configurable": {"thread_id": "tg:42:v1"}},
        )
        self.assertEqual(
            graph.ainvoke.await_args_list[1].kwargs["config"],
            {"configurable": {"thread_id": "tg:99:v0"}},
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
