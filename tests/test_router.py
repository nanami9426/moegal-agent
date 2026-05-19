import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

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


if __name__ == "__main__":
    unittest.main()
