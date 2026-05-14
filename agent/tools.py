from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from services.subscriptions import (
    create_subscription as create_subscription_record,
)
from services.subscriptions import list_subscriptions as list_subscription_records


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


TOOLS = [create_subscription, list_subscriptions]
