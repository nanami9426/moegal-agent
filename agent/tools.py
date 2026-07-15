from typing import Annotated
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from services.account.memories import (
    forget_memory as forget_memory_record,
    list_memories as list_memory_records,
    remember_memory as remember_memory_record,
)
from services.account.subscriptions import (
    create_subscription as create_subscription_record,
    delete_subscription as delete_subscription_record,
)
from services.account.subscriptions import list_subscriptions as list_subscription_records
from services.rss_pipeline.digest import build_daily_digest as build_daily_digest_text


@tool
def create_subscription(
    target: str,
    user_id: Annotated[int, InjectedState("user_id")],
    type: str = "keyword",
) -> str:
    """Create or re-enable a user's subscription for a target keyword or source."""
    result = create_subscription_record(user_id=user_id, target=target, type=type)
    subscription = result.subscription

    if result.created:
        return f"已订阅：{subscription.target}。之后会在每日摘要里优先推送相关内容。"

    if result.reenabled:
        return f"已重新启用订阅：{subscription.target}。"

    return f"已订阅过：{subscription.target}。我不会重复创建。"


@tool
def delete_subscription(
    target: str,
    user_id: Annotated[int, InjectedState("user_id")],
    type: str = "keyword",
) -> str:
    """Delete or disable a user's active subscription for a target keyword or source."""
    result = delete_subscription_record(user_id=user_id, target=target, type=type)

    if result.deleted and result.subscription is not None:
        return f"已取消订阅：{result.subscription.target}。"

    return f"没有找到有效订阅：{target}。"


@tool
def list_subscriptions(
    user_id: Annotated[int, InjectedState("user_id")],
) -> str:
    """List the user's active subscriptions."""
    subscriptions = list_subscription_records(user_id=user_id)

    if not subscriptions:
        return "你现在还没有订阅。可以说“帮我订阅 xxx”来添加。"

    lines = [
        f"{index}. {subscription.display_name or subscription.target}"
        for index, subscription in enumerate(subscriptions, start=1)
    ]
    return "当前订阅：\n" + "\n".join(lines)


@tool
def build_daily_digest(
    user_id: Annotated[int, InjectedState("user_id")],
) -> str:
    """Read cached RSS entries, match subscriptions, and build the user's daily digest."""
    return build_daily_digest_text(user_id=user_id)


@tool
def remember_user_memory(
    key: str,
    content: str,
    user_id: Annotated[int, InjectedState("user_id")],
    memory_enabled: Annotated[bool, InjectedState("memory_enabled")],
    kind: str = "note",
    source: str = "explicit",
    confidence: float = 1.0,
    importance: float = 0.5,
) -> str:
    """Store or update a long-term memory about the current user.

    Use this when the user asks you to remember something, gives a stable preference,
    or corrects profile/preference information that should persist across chats.
    kind should be one of: profile, preference, dislike, note.
    source should be explicit for user-stated facts and inferred for deductions.
    Use lower confidence for inferred memories. importance is between 0 and 1.
    """
    if not memory_enabled:
        return "临时对话不会保存长期记忆。"

    try:
        result = remember_memory_record(
            user_id=user_id,
            kind=kind,
            key=key,
            content=content,
            source=source,
            confidence=confidence,
            importance=importance,
        )
    except ValueError as exc:
        return f"无法保存记忆：{exc}"

    if result.created:
        return f"已记住：{result.memory.content}"

    if result.reactivated:
        return f"已恢复并更新记忆：{result.memory.content}"

    return f"已更新记忆：{result.memory.content}"


@tool
def forget_user_memory(
    key: str,
    user_id: Annotated[int, InjectedState("user_id")],
    memory_enabled: Annotated[bool, InjectedState("memory_enabled")],
    kind: str = "",
) -> str:
    """Forget a long-term memory about the current user.

    Use this when the user asks you to forget or delete remembered information.
    Leave kind empty if the user did not specify the memory category.
    """
    if not memory_enabled:
        return "临时对话不会读取或修改长期记忆。"

    try:
        forgotten_count = forget_memory_record(
            user_id=user_id,
            key=key,
            kind=kind or None,
        )
    except ValueError as exc:
        return f"无法忘记记忆：{exc}"

    if forgotten_count == 0:
        return f"没有找到关于「{key}」的有效记忆。"

    return f"已忘记关于「{key}」的记忆。"


@tool
def list_user_memories(
    user_id: Annotated[int, InjectedState("user_id")],
    memory_enabled: Annotated[bool, InjectedState("memory_enabled")],
    limit: int = 20,
) -> str:
    """List active long-term memories stored for the current user."""
    if not memory_enabled:
        return "临时对话不会读取长期记忆。"
    memories = list_memory_records(user_id=user_id, limit=limit)
    if not memories:
        return "我还没有保存你的长期记忆。"

    lines = [
        f"{index}. [{memory.kind}] {memory.key}: {memory.content}"
        for index, memory in enumerate(memories, start=1)
    ]
    return "当前长期记忆：\n" + "\n".join(lines)


@tool
def get_weather(location: str = "Shenzhen") -> str:
    """Get the current weather for a city or region. Use this when the user asks about weather."""
    normalized_location = " ".join(location.strip().split())
    if not normalized_location:
        normalized_location = "Shenzhen"
    normalized_location = normalized_location[:80]
    url = f"https://wttr.in/{quote(normalized_location, safe='')}"

    try:
        response = httpx.get(
            url,
            params={
                "format": "%l: %C %t, 体感%f, 湿度%h, 风%w, 降水%p, 紫外线%u",
                "lang": "zh",
            },
            timeout=8.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return f"查询 {normalized_location} 天气失败：天气服务返回 {exc.response.status_code}。"
    except httpx.HTTPError as exc:
        return f"查询 {normalized_location} 天气失败：{exc}。"

    weather = response.text.strip()
    if not weather:
        return f"查询 {normalized_location} 天气失败：天气服务没有返回内容。"

    return weather


TOOLS = [
    create_subscription,
    delete_subscription,
    list_subscriptions,
    build_daily_digest,
    remember_user_memory,
    forget_user_memory,
    list_user_memories,
    get_weather,
]
