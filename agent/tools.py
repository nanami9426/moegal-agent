from typing import Annotated
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

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
    get_weather,
]
