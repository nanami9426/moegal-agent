from threading import Lock
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from typing import Any

from agent.graph import chat_graph


_context_versions: dict[str, int] = {}
_context_versions_lock = Lock()


def _conversation_key(platform: str, platform_user_id: str) -> str:
    return f"{platform}:{platform_user_id}"


def _thread_id(platform: str, platform_user_id: str) -> str:
    key = _conversation_key(platform, platform_user_id)
    with _context_versions_lock:
        version = _context_versions.get(key, 0)
    return f"{key}:v{version}"


def start_new_conversation_context(platform: str, platform_user_id: str) -> str:
    key = _conversation_key(platform, platform_user_id)
    with _context_versions_lock:
        version = _context_versions.get(key, 0) + 1
        _context_versions[key] = version
    return f"{key}:v{version}"

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

def extract_final_text(messages: list[BaseMessage]) -> str:
    # 从消息列表里找出最终可以发给用户的文本
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = _content_to_text(message.content)
            if text:
                return text

    return "我现在没有生成可发送的回复。"

async def route_message(
    platform: str,
    platform_user_id: str,
    text: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
) -> str:
    text = text.strip()

    if not text:
        return "你可以发送文本。"

    result = await chat_graph.ainvoke(
        {
            "messages": [HumanMessage(content=text)],
            "platform": platform,
            "platform_user_id": platform_user_id,
            "user_id": None,
            "username": username,
            "display_name": display_name,
            "language_code": language_code,
        },
        config={"configurable": {"thread_id": _thread_id(platform, platform_user_id)}},
    )

    return extract_final_text(result["messages"])
