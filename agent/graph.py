import asyncio
import os
from contextlib import AsyncExitStack
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.state import MoegalState
from agent.tools import TOOLS
from db.session import get_psycopg_conninfo
from services.account.users import upsert_user
from utils.llm import get_base_url, llm_user_headers


SYSTEM_PROMPT = """你是鸽酱，一个面向二次元用户的智能助手。
会积极解决用户的问题，给用户提供情绪价值，也懂得主动向用户发起话题。
用简短、自然的中文回复，不要复读用户原文。
"""


def prepare_context(state: MoegalState) -> dict[str, Any]:
    # router 已经落库并传入 user_id 时，避免在图节点里重复 upsert 用户。
    if state.get("user_id") is not None:
        return {"user_id": state["user_id"]}

    user = upsert_user(
        platform=state["platform"],
        platform_user_id=state["platform_user_id"],
        # ↑必须有的字段，↓附加资料
        username=state.get("username"),
        display_name=state.get("display_name"),
        language_code=state.get("language_code"),
    )
    return {"user_id": user.id}


@lru_cache
def _get_model_with_tools() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. 请先在 .env 中配置。")

    model = ChatOpenAI(
        model=os.getenv("MOEGAL_MODEL"),
        api_key=api_key,
        base_url=get_base_url(),
        temperature=0.6,
        stream_usage=True,
    )
    return model.bind_tools(TOOLS)


async def call_model(state: MoegalState) -> dict[str, list[BaseMessage]]:
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    response = await _get_model_with_tools().ainvoke(
        messages,
        extra_headers=llm_user_headers(state.get("user_id")),
    )
    return {"messages": [response]}


def build_chat_graph(checkpointer: Any):
    builder = StateGraph(MoegalState)
    builder.add_node("prepare_context", prepare_context)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(TOOLS))

    builder.add_edge(START, "prepare_context")
    builder.add_edge("prepare_context", "agent")
    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: END,
        },
    )
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer)


# AsyncPostgresSaver 持有异步连接资源，按 event loop 缓存，避免跨 loop 复用连接。
_chat_graphs: dict[int, Any] = {}
_chat_graph_stacks: dict[int, AsyncExitStack] = {}
_chat_graph_locks: dict[int, asyncio.Lock] = {}


async def get_chat_graph() -> Any:
    loop_id = id(asyncio.get_running_loop())
    graph = _chat_graphs.get(loop_id)
    if graph is not None:
        return graph

    lock = _chat_graph_locks.setdefault(loop_id, asyncio.Lock())
    async with lock:
        # 双重检查，防止同一个 loop 内并发首个请求重复创建 graph。
        graph = _chat_graphs.get(loop_id)
        if graph is not None:
            return graph

        stack = AsyncExitStack()
        try:
            # 连接池会在借出连接时做健康检查，避免长期运行后复用已关闭连接。
            pool = await stack.enter_async_context(
                AsyncConnectionPool(get_psycopg_conninfo(),
                                    kwargs={
                                        "autocommit": True,
                                        "prepare_threshold": 0,
                                        "row_factory": dict_row,
                                        },
                                    min_size=0,
                                    max_size=4,
                                    max_idle=60.0,
                                    check=AsyncConnectionPool.check_connection,
                                    open=False,))
            checkpointer = AsyncPostgresSaver(pool)
            # setup 是幂等的，会创建/迁移 LangGraph checkpoint 表。
            await checkpointer.setup()
            graph = build_chat_graph(checkpointer)
            _chat_graph_stacks[loop_id] = stack
            _chat_graphs[loop_id] = graph
            return graph
        except Exception:
            await stack.aclose()
            raise


async def close_chat_graphs() -> None:
    for loop_id, stack in list(_chat_graph_stacks.items()):
        _chat_graph_stacks.pop(loop_id, None)
        _chat_graphs.pop(loop_id, None)
        _chat_graph_locks.pop(loop_id, None)
        await stack.aclose()
