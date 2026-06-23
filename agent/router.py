import base64
import os
from functools import lru_cache
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.graph import get_chat_graph
from services.account.conversations import (
    append_message,
    get_or_create_active_conversation,
    start_new_conversation,
)
from services.account.users import upsert_user
from utils.llm import get_base_url


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
) -> str:
    # /newchat 会生成新的会话版本，旧版本仍保留在数据库中用于追溯。
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    conversation = start_new_conversation(
        user_id=user.id,
        platform=platform,
        platform_user_id=platform_user_id,
    )
    return conversation.thread_id


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

    reply_text = extract_final_text(result["messages"])
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
) -> str:
    if not image_bytes:
        return "图片为空，无法识别。"

    _ = (platform, platform_user_id, username, display_name, language_code)
    image_prompt = (prompt or "").strip() or DEFAULT_IMAGE_PROMPT
    b64_image = base64.b64encode(image_bytes).decode("utf8")
    image_url = f"data:{mime_type};base64,{b64_image}"
    response = await _get_image_model().ainvoke(
        [
            SystemMessage(content=IMAGE_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "text", "text": image_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]
            ),
        ]
    )

    text = _content_to_text(response.content)
    return text or "我现在没有生成可发送的回复。"


async def classify_image_translation_intent(text: str) -> ImageTranslationIntent:
    text = text.strip()
    if not text:
        return "unknown"

    response = await _get_intent_model().ainvoke(
        [
            SystemMessage(content=IMAGE_TRANSLATION_INTENT_SYSTEM_PROMPT),
            HumanMessage(content=text),
        ]
    )
    label = _content_to_text(response.content).strip().lower()
    if label in ("translate", "skip", "unknown"):
        return label

    return "unknown"
