import base64
import os
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.graph import get_chat_graph
from services.account.conversations import (
    NewConversationResult,
    append_message,
    get_or_create_active_conversation,
    start_new_conversation,
)
from services.account.memories import build_memory_context
from services.account.users import upsert_user
from utils.llm import get_base_url, llm_user_headers


IMAGE_SYSTEM_PROMPT = """你是 Moegal Agent，一个面向二次元用户的轻量助手。
你可以理解图片内容。用简短、自然的中文回答，优先回应用户随图提出的问题。"""
DEFAULT_IMAGE_PROMPT = "请用简短、自然的中文描述这张图片，并回答用户可能想知道的重点。"
ImageTranslationIntent = Literal["translate", "skip", "unknown"]
IMAGE_TRANSLATION_INTENT_SYSTEM_PROMPT = """你是一个严格的意图分类器。
任务：判断用户在当前上下文中是否希望翻译图片。

上下文可能包括：
- 用户刚发送图片，正在用 caption 或后续消息表达意图。
- 机器人刚询问用户是否需要翻译一张漫画图。

只输出以下三个标签之一，不要输出解释：
- translate：用户想翻译当前图片，或同意翻译当前图片。
- skip：用户不想翻译图片，或表示不用、不要、先别翻译。
- unknown：用户意图不明确，或并不是在表达图片翻译意图。
"""


def start_new_conversation_context(
    platform: str,
    platform_user_id: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
) -> NewConversationResult:
    # /newchat 只在当前会话已有消息时切换版本，避免生成空会话记录。
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    return start_new_conversation(
        user_id=user.id,
        platform=platform,
        platform_user_id=platform_user_id,
    )


def _content_to_text(content: str | list[Any] | None) -> str:
    if content is None:
        return ""
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


def extract_final_text(messages: list[BaseMessage]) -> str | None:
    # 从消息列表里找出最终可以发给用户的文本；找不到返回 None，由调用方兜底占位串。
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = _content_to_text(message.content)
            if text:
                return text

    return None


@lru_cache
def _get_image_model() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. 请先在 .env 中配置。")

    return ChatOpenAI(
        model=os.getenv("MOEGAL_MODEL"),
        api_key=api_key,
        base_url=get_base_url(),
        temperature=0.6,
    )


@lru_cache
def _get_intent_model() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. 请先在 .env 中配置。")

    return ChatOpenAI(
        model=os.getenv("MOEGAL_MODEL"),
        api_key=api_key,
        base_url=get_base_url(),
        temperature=0,
    )


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

    # 先确保平台用户存在，再用 active conversation 的 thread_id 续接上下文。
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    conversation = get_or_create_active_conversation(
        user_id=user.id,
        platform=platform,
        platform_user_id=platform_user_id,
    )
    # messages 表保存可读聊天日志；LangGraph checkpoint 负责模型上下文恢复。
    append_message(
        conversation_id=conversation.id,
        role="user",
        content=text,
        metadata_json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "thread_id": conversation.thread_id,
        },
    )

    chat_graph = await get_chat_graph()
    # thread_id 是 LangGraph 读取/写入 checkpoint 的会话隔离键。
    result = await chat_graph.ainvoke(
        {
            "messages": [HumanMessage(content=text)],
            "platform": platform,
            "platform_user_id": platform_user_id,
            "user_id": user.id,
            "username": username,
            "display_name": display_name,
            "language_code": language_code,
        },
        config={"configurable": {"thread_id": conversation.thread_id}},
    )

    reply_text = extract_final_text(result["messages"]) or "我现在没有生成可发送的回复。"
    # 只记录最终要发给用户的助手回复，不把中间 tool call 展示为聊天记录。
    append_message(
        conversation_id=conversation.id,
        role="assistant",
        content=reply_text,
        metadata_json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "thread_id": conversation.thread_id,
        },
    )
    return reply_text


async def route_message_stream(
    platform: str,
    platform_user_id: str,
    text: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
) -> AsyncIterator[str]:
    text = text.strip()

    if not text:
        yield "你可以发送文本。"
        return

    # 流式接口复用同一套会话和消息落库逻辑，只把模型 token 提前吐给前端。
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    conversation = get_or_create_active_conversation(
        user_id=user.id,
        platform=platform,
        platform_user_id=platform_user_id,
    )
    append_message(
        conversation_id=conversation.id,
        role="user",
        content=text,
        metadata_json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "thread_id": conversation.thread_id,
        },
    )

    chat_graph = await get_chat_graph()
    final_messages: list[BaseMessage] | None = None
    streamed_parts: list[str] = []

    async for mode, data in chat_graph.astream(
        {
            "messages": [HumanMessage(content=text)],
            "platform": platform,
            "platform_user_id": platform_user_id,
            "user_id": user.id,
            "username": username,
            "display_name": display_name,
            "language_code": language_code,
        },
        config={"configurable": {"thread_id": conversation.thread_id}},
        stream_mode=["messages", "values"],
    ):
        if mode == "values":
            messages = data.get("messages") if isinstance(data, dict) else None
            if isinstance(messages, list):
                final_messages = messages
            continue

        if mode != "messages":
            continue

        message_chunk, metadata = data
        if metadata.get("langgraph_node") != "agent":
            continue
        # 工具调用分片不是给用户看的文本，跳过后等待工具结果后的最终回复。
        if (
            getattr(message_chunk, "tool_call_chunks", None)
            or getattr(message_chunk, "tool_calls", None)
        ):
            continue

        content = message_chunk.content
        if isinstance(content, str):
            chunk_text = content
        elif isinstance(content, list):
            chunk_parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunk_parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunk_parts.append(item["text"])
                else:
                    chunk_parts.append(str(item))
            chunk_text = "".join(chunk_parts)
        else:
            chunk_text = ""
        if not chunk_text:
            continue

        streamed_parts.append(chunk_text)
        yield chunk_text

    reply_text = extract_final_text(final_messages or [])
    if reply_text is None:
        if streamed_parts:
            reply_text = "".join(streamed_parts).strip() or "我现在没有生成可发送的回复。"
        else:
            reply_text = "我现在没有生成可发送的回复。"

    append_message(
        conversation_id=conversation.id,
        role="assistant",
        content=reply_text,
        metadata_json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "thread_id": conversation.thread_id,
        },
    )


async def route_image_message(
    platform: str,
    platform_user_id: str,
    image_bytes: bytes,
    *,
    prompt: str | None = None,
    mime_type: str = "image/jpeg",
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
    user_id: int | None = None,
) -> str:
    if not image_bytes:
        return "图片为空，无法识别。"

    if user_id is None:
        user = upsert_user(
            platform=platform,
            platform_user_id=platform_user_id,
            username=username,
            display_name=display_name,
            language_code=language_code,
        )
        user_id = user.id

    image_prompt = (prompt or "").strip() or DEFAULT_IMAGE_PROMPT
    b64_image = base64.b64encode(image_bytes).decode("utf8")
    image_url = f"data:{mime_type};base64,{b64_image}"
    messages: list[BaseMessage] = [SystemMessage(content=IMAGE_SYSTEM_PROMPT)]
    memory_context = build_memory_context(user_id)
    if memory_context:
        messages.append(
            SystemMessage(
                content=(
                    "当前用户的长期记忆如下。回答图片问题时可以参考；"
                    "如果与用户本轮图片或文字冲突，优先相信本轮内容。\n"
                    f"{memory_context}"
                )
            )
        )
    messages.append(
        HumanMessage(
            content=[
                {"type": "text", "text": image_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        )
    )
    response = await _get_image_model().ainvoke(
        messages,
        extra_headers=llm_user_headers(user_id),
    )

    text = _content_to_text(response.content)
    return text or "我现在没有生成可发送的回复。"


async def classify_image_translation_intent(text: str, *, user_id: int) -> ImageTranslationIntent:
    text = text.strip()
    if not text:
        return "unknown"

    response = await _get_intent_model().ainvoke(
        [
            SystemMessage(content=IMAGE_TRANSLATION_INTENT_SYSTEM_PROMPT),
            HumanMessage(content=text),
        ],
        extra_headers=llm_user_headers(user_id),
    )
    label = _content_to_text(response.content).strip().lower()
    if label in ("translate", "skip", "unknown"):
        return label

    return "unknown"
