import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from agent import graph as agent_graph
from agent import router


class _FakeAsyncPool:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.exit_count += 1


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

    async def test_route_message_stream_yields_chunks_and_stores_final_reply(self) -> None:
        async def graph_stream(*args, **kwargs):
            yield (
                "messages",
                (
                    AIMessageChunk(content="你"),
                    {"langgraph_node": "agent"},
                ),
            )
            yield (
                "messages",
                (
                    AIMessageChunk(content="好"),
                    {"langgraph_node": "agent"},
                ),
            )
            yield (
                "values",
                {
                    "messages": [
                        HumanMessage(content="你好"),
                        AIMessage(content="你好"),
                    ]
                },
            )

        graph = SimpleNamespace(astream=graph_stream)
        conversation = SimpleNamespace(
            id=1,
            thread_id="00000000-0000-4000-8000-000000000001",
        )

        with (
            patch.object(router, "upsert_user", return_value=SimpleNamespace(id=1001)),
            patch.object(router, "get_or_create_active_conversation", return_value=conversation),
            patch.object(router, "append_message") as append_message_mock,
            patch.object(router, "get_chat_graph", AsyncMock(return_value=graph)),
        ):
            chunks = [
                chunk
                async for chunk in router.route_message_stream("web", "42", "  你好  ")
            ]

        self.assertEqual(chunks, ["你", "好"])
        self.assertEqual(append_message_mock.call_count, 2)
        self.assertEqual(append_message_mock.call_args_list[0].kwargs["content"], "你好")
        self.assertEqual(append_message_mock.call_args_list[1].kwargs["content"], "你好")

    async def test_call_model_sends_x_user_id_header(self) -> None:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="ok")))

        with patch.object(agent_graph, "_get_model_with_tools", return_value=model):
            result = await agent_graph.call_model(
                {
                    "messages": [HumanMessage(content="你好")],
                    "platform": "tg",
                    "platform_user_id": "42",
                    "user_id": 1_000_000_001,
                    "username": None,
                    "display_name": None,
                    "language_code": None,
                }
            )

        self.assertEqual(result, {"messages": [AIMessage(content="ok")]})
        model.ainvoke.assert_awaited_once()
        self.assertEqual(
            model.ainvoke.await_args.kwargs["extra_headers"],
            {"X-User-ID": "1000000001"},
        )

    async def test_get_chat_graph_uses_checked_connection_pool(self) -> None:
        await agent_graph.close_chat_graphs()
        fake_pool = _FakeAsyncPool()
        fake_saver = SimpleNamespace(setup=AsyncMock())
        fake_graph = SimpleNamespace()
        check_connection = object()
        pool_factory = Mock(return_value=fake_pool)
        pool_factory.check_connection = check_connection

        with (
            patch.object(agent_graph, "get_psycopg_conninfo", return_value="postgresql://db"),
            patch.object(agent_graph, "AsyncConnectionPool", pool_factory),
            patch.object(agent_graph, "AsyncPostgresSaver", Mock(return_value=fake_saver)),
            patch.object(agent_graph, "build_chat_graph", Mock(return_value=fake_graph)),
        ):
            graph = await agent_graph.get_chat_graph()

        self.assertIs(graph, fake_graph)
        self.assertEqual(fake_pool.enter_count, 1)
        fake_saver.setup.assert_awaited_once()
        pool_factory.assert_called_once_with(
            "postgresql://db",
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": agent_graph.dict_row,
            },
            min_size=0,
            max_size=4,
            max_idle=60.0,
            check=check_connection,
            open=False,
        )

        await agent_graph.close_chat_graphs()
        self.assertEqual(fake_pool.exit_count, 1)

    async def test_get_chat_graph_closes_pool_when_setup_fails(self) -> None:
        await agent_graph.close_chat_graphs()
        fake_pool = _FakeAsyncPool()
        fake_saver = SimpleNamespace(setup=AsyncMock(side_effect=RuntimeError("setup failed")))
        pool_factory = Mock(return_value=fake_pool)
        pool_factory.check_connection = object()

        with (
            patch.object(agent_graph, "get_psycopg_conninfo", return_value="postgresql://db"),
            patch.object(agent_graph, "AsyncConnectionPool", pool_factory),
            patch.object(agent_graph, "AsyncPostgresSaver", Mock(return_value=fake_saver)),
            self.assertRaisesRegex(RuntimeError, "setup failed"),
        ):
            await agent_graph.get_chat_graph()

        self.assertEqual(fake_pool.exit_count, 1)
        self.assertEqual(agent_graph._chat_graphs, {})
        self.assertEqual(agent_graph._chat_graph_stacks, {})

    async def test_route_image_message_builds_multimodal_message(self) -> None:
        image_bytes = b"image-bytes"
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="图片回答")))

        with (
            patch.object(router, "upsert_user", return_value=SimpleNamespace(id=1_000_000_001)),
            patch.object(router, "_get_image_model", return_value=model),
        ):
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
        self.assertEqual(
            model.ainvoke.await_args.kwargs["extra_headers"],
            {"X-User-ID": "1000000001"},
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
            result = await router.classify_image_translation_intent(
                "不用翻译了啊",
                user_id=1_000_000_001,
            )

        self.assertEqual(result, "skip")
        model.ainvoke.assert_awaited_once()
        messages = model.ainvoke.await_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIsInstance(messages[1], HumanMessage)
        self.assertEqual(messages[1].content, "不用翻译了啊")
        self.assertEqual(
            model.ainvoke.await_args.kwargs["extra_headers"],
            {"X-User-ID": "1000000001"},
        )

    async def test_classify_image_translation_intent_returns_unknown_for_bad_label(self) -> None:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="maybe")))

        with patch.object(router, "_get_intent_model", return_value=model):
            result = await router.classify_image_translation_intent(
                "等一下",
                user_id=1_000_000_001,
            )

        self.assertEqual(result, "unknown")


if __name__ == "__main__":
    unittest.main()
