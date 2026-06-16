import base64
import os
from functools import lru_cache
from threading import Lock
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.graph import chat_graph


_context_versions: dict[str, int] = {}
_context_versions_lock = Lock()
IMAGE_SYSTEM_PROMPT = """你是 Moegal Agent，一个面向二次元用户的轻量助手。
你可以理解图片内容。用简短、自然的中文回答，优先回应用户随图提出的问题。"""
DEFAULT_IMAGE_PROMPT = "请用简短、自然的中文描述这张图片，并回答用户可能想知道的重点。"
ImageTranslationIntent = Literal["translate", "skip", "unknown"]
IMAGE_TRANSLATION_INTENT_SYSTEM_PROMPT = """你是一个严格的意图分类器。
任务：判断用户在当前上下文中是否希望翻译图片。

上下文可能包括：
- 用户刚发送图片，正在用 caption 或后续消息表达意图。
- 机器人刚询问用户是否需要翻译一张漫画图。
- 用户尚未发送图片，但在请求下一张图片进入翻译流程。

只输出以下三个标签之一，不要输出解释：
- translate：用户想翻译图片、请求翻译下一张图片，或同意翻译。
- skip：用户不想翻译图片，或表示不用、不要、先别翻译。
- unknown：用户意图不明确，或并不是在表达图片翻译意图。
"""


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


@lru_cache
def _get_image_model() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. 请先在 .env 中配置。")

    return ChatOpenAI(
        model=os.getenv("MOEGAL_MODEL"),
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
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
        base_url=os.getenv("OPENAI_BASE_URL") or None,
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
