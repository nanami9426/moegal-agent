import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.graph import call_model, prepare_context


class AgentMemoryTest(unittest.IsolatedAsyncioTestCase):
    def test_prepare_context_refreshes_memory_for_existing_user(self) -> None:
        with patch(
            "agent.graph.build_memory_context",
            return_value="- kind=preference; key=studio; content=用户喜欢芳文社。",
        ) as build_memory_context:
            result = prepare_context(
                {
                    "messages": [],
                    "platform": "tg",
                    "platform_user_id": "42",
                    "user_id": 1_000_000_001,
                }
            )

        self.assertEqual(result["user_id"], 1_000_000_001)
        self.assertIn("用户喜欢芳文社", result["memory_context"])
        build_memory_context.assert_called_once_with(1_000_000_001)

    async def test_call_model_includes_memory_context(self) -> None:
        fake_model = _FakeModel()
        with (
            patch("agent.graph._get_model_with_tools", return_value=fake_model),
            patch("agent.graph.llm_user_headers", return_value={"x-user-id": "1"}),
        ):
            result = await call_model(
                {
                    "messages": [HumanMessage(content="推荐一部动画")],
                    "user_id": 1_000_000_001,
                    "memory_context": "- kind=preference; key=studio; content=用户喜欢芳文社。",
                }
            )

        self.assertEqual(result["messages"][0].content, "ok")
        self.assertEqual(fake_model.kwargs["extra_headers"], {"x-user-id": "1"})
        self.assertIsInstance(fake_model.messages[0], SystemMessage)
        self.assertIsInstance(fake_model.messages[1], SystemMessage)
        self.assertIn("用户喜欢芳文社", fake_model.messages[1].content)
        self.assertIsInstance(fake_model.messages[-1], HumanMessage)

    async def test_call_model_skips_empty_memory_context(self) -> None:
        fake_model = _FakeModel()
        with (
            patch("agent.graph._get_model_with_tools", return_value=fake_model),
            patch("agent.graph.llm_user_headers", return_value={}),
        ):
            await call_model(
                {
                    "messages": [HumanMessage(content="你好")],
                    "user_id": 1_000_000_001,
                    "memory_context": "",
                }
            )

        system_messages = [
            message for message in fake_model.messages
            if isinstance(message, SystemMessage)
        ]
        self.assertEqual(len(system_messages), 1)


class _FakeModel:
    def __init__(self) -> None:
        self.messages = []
        self.kwargs = {}

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        self.messages = messages
        self.kwargs = kwargs
        return AIMessage(content="ok")


if __name__ == "__main__":
    unittest.main()
