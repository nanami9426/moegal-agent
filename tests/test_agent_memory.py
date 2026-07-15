import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_chat_graph, call_model, prepare_context


class AgentMemoryTest(unittest.IsolatedAsyncioTestCase):
    def test_prepare_context_refreshes_memory_for_existing_user(self) -> None:
        with patch(
            "agent.graph.build_memory_context",
            return_value="- kind=preference; key=studio; content=用户喜欢芳文社。",
        ) as build_memory_context, patch(
            "agent.graph.get_memory_settings",
            return_value=type(
                "Settings",
                (),
                {"enabled": True, "use_chat_history": True},
            )(),
        ):
            result = prepare_context(
                {
                    "messages": [HumanMessage(content="推荐一部动画")],
                    "platform": "tg",
                    "platform_user_id": "42",
                    "user_id": 1_000_000_001,
                }
            )

        self.assertEqual(result["user_id"], 1_000_000_001)
        self.assertIn("用户喜欢芳文社", result["memory_context"])
        build_memory_context.assert_called_once_with(
            1_000_000_001,
            query="推荐一部动画",
            namespaces=["global", "platform:tg"],
            include_chat_history=True,
            exclude_conversation_id=None,
        )

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

    def test_prepare_context_respects_disabled_memory_setting(self) -> None:
        with (
            patch(
                "agent.graph.get_memory_settings",
                return_value=type("Settings", (), {"enabled": False})(),
            ),
            patch("agent.graph.build_memory_context") as build_memory_context,
        ):
            result = prepare_context(
                {
                    "messages": [HumanMessage(content="你好")],
                    "platform": "web",
                    "platform_user_id": "42",
                    "user_id": 1_000_000_001,
                    "memory_enabled": True,
                }
            )

        self.assertFalse(result["memory_enabled"])
        self.assertEqual(result["memory_context"], "")
        build_memory_context.assert_not_called()

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

    async def test_call_model_trims_old_messages_to_context_budget(self) -> None:
        fake_model = _FakeModel()
        old_message = "旧消息" * 5000
        with (
            patch("agent.graph._get_model_with_tools", return_value=fake_model),
            patch("agent.graph._get_context_max_tokens", return_value=1000),
            patch("agent.graph.llm_user_headers", return_value={}),
        ):
            await call_model(
                {
                    "messages": [
                        HumanMessage(content=old_message),
                        AIMessage(content="旧回复" * 5000),
                        HumanMessage(content="这是最新问题"),
                    ],
                    "user_id": 1_000_000_001,
                    "memory_context": "",
                }
            )

        human_contents = [
            message.content
            for message in fake_model.messages
            if isinstance(message, HumanMessage)
        ]
        self.assertIn("这是最新问题", human_contents)
        self.assertNotIn(old_message, human_contents)

    async def test_temporary_graph_keeps_only_process_local_thread_context(self) -> None:
        model = _RecordingModel()
        graph = build_chat_graph(InMemorySaver())
        state = {
            "platform": "web",
            "platform_user_id": "42",
            "user_id": 1_000_000_001,
            "conversation_id": None,
            "memory_enabled": False,
        }
        with (
            patch("agent.graph._get_model_with_tools", return_value=model),
            patch("agent.graph.llm_user_headers", return_value={}),
        ):
            await graph.ainvoke(
                {**state, "messages": [HumanMessage(content="临时第一问")]},
                config={"configurable": {"thread_id": "temporary:1:a"}},
            )
            await graph.ainvoke(
                {**state, "messages": [HumanMessage(content="临时第二问")]},
                config={"configurable": {"thread_id": "temporary:1:a"}},
            )
            await graph.ainvoke(
                {**state, "messages": [HumanMessage(content="另一个临时会话")]},
                config={"configurable": {"thread_id": "temporary:1:b"}},
            )

        second_human_messages = [
            message.content
            for message in model.calls[1]
            if isinstance(message, HumanMessage)
        ]
        third_human_messages = [
            message.content
            for message in model.calls[2]
            if isinstance(message, HumanMessage)
        ]
        self.assertEqual(second_human_messages, ["临时第一问", "临时第二问"])
        self.assertEqual(third_human_messages, ["另一个临时会话"])


class _FakeModel:
    def __init__(self) -> None:
        self.messages = []
        self.kwargs = {}

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        self.messages = messages
        self.kwargs = kwargs
        return AIMessage(content="ok")


class _RecordingModel:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        self.calls.append(list(messages))
        return AIMessage(content="ok")


if __name__ == "__main__":
    unittest.main()
