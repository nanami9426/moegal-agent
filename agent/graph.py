import os
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.state import MoegalState
from agent.tools import TOOLS
from services.account.users import upsert_user


SYSTEM_PROMPT = """你是 Moegal Agent，一个面向二次元用户的轻量助手。
用简短、自然的中文回复，不要复读用户原文。
第一版支持基于 RSS/RSSHub 的订阅摘要，但还没有主动实时推送和图片理解能力。"""


def prepare_context(state: MoegalState) -> dict[str, Any]:
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
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        temperature=0.6,
    )
    return model.bind_tools(TOOLS)


async def call_model(state: MoegalState) -> dict[str, list[BaseMessage]]:
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    response = await _get_model_with_tools().ainvoke(messages)
    return {"messages": [response]}


def build_chat_graph():
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

    return builder.compile(checkpointer=InMemorySaver())


chat_graph = build_chat_graph()


def extract_final_text(messages: list[BaseMessage]) -> str:
    # 从消息列表里找出最终可以发给用户的文本
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = _content_to_text(message.content)
            if text:
                return text

    return "我现在没有生成可发送的回复。"


def _content_to_text(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content.strip()

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
        else:
            parts.append(str(item))

    return "\n".join(part.strip() for part in parts if part).strip()
