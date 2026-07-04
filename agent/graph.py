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

from agent.state import MoegalState
from agent.tools import TOOLS
from db.session import get_psycopg_conninfo
from services.account.users import upsert_user
from utils.llm import get_base_url, llm_user_headers


SYSTEM_PROMPT = """你是 Moegal Agent，一个面向二次元用户的轻量助手。
用简短、自然的中文回复，不要复读用户原文。
第一版支持基于 RSS/RSSHub 的订阅摘要，可以添加、查看、取消关键词订阅，但还没有主动实时推送能力。"""


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


# AsyncPostgresSaver 持有异步连接，按 event loop 缓存，避免跨 loop 复用连接。
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
        # stack 负责持有 saver 的数据库连接，进程退出或测试收尾时统一关闭。
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(get_psycopg_conninfo())
        )
        # setup 是幂等的，会创建/迁移 LangGraph checkpoint 表。
        await checkpointer.setup()
        graph = build_chat_graph(checkpointer)
        _chat_graph_stacks[loop_id] = stack
        _chat_graphs[loop_id] = graph
        return graph


async def close_chat_graphs() -> None:
    for loop_id, stack in list(_chat_graph_stacks.items()):
        await stack.aclose()
        _chat_graph_stacks.pop(loop_id, None)
        _chat_graphs.pop(loop_id, None)
        _chat_graph_locks.pop(loop_id, None)
