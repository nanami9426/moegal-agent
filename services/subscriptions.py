from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import Subscription, utc_now
from db.session import get_engine

# 创建后变为只读 frozen=True
@dataclass(frozen=True)
class SubscriptionResult:
    subscription: Subscription
    created: bool
    reenabled: bool = False


def create_subscription(user_id: int, target: str,
                        *,
                        type: str = "keyword", display_name: str | None = None) -> SubscriptionResult:
    # 先只支持 keyword
    subscription_type = type.strip() or "keyword"
    if subscription_type != "keyword":
        subscription_type = "keyword"
    normalized_target = target.strip()

    if not normalized_target:
        raise ValueError("subscription target is required.")

    with Session(get_engine()) as session:
        subscription = session.exec(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.type == subscription_type,
                Subscription.target == normalized_target,
            )
        ).first()

        now = utc_now()
        if subscription is not None:
            was_disabled = not subscription.enabled
            subscription.enabled = True
            subscription.display_name = display_name or subscription.display_name or normalized_target
            subscription.delivery_mode = "daily"
            subscription.updated_at = now
            session.add(subscription)
            session.commit()
            session.refresh(subscription)
            return SubscriptionResult(
                subscription=subscription,
                created=False,
                reenabled=was_disabled,
            )

        subscription = Subscription(
            user_id=user_id,
            type=subscription_type,
            target=normalized_target,
            display_name=display_name or normalized_target,
            enabled=True,
            delivery_mode="daily",
        )
        session.add(subscription)

        try:
            session.commit()
        except IntegrityError:
            # 处理并发创建冲突
            session.rollback()
            subscription = session.exec(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.type == subscription_type,
                    Subscription.target == normalized_target,
                )
            ).one()
            return SubscriptionResult(subscription=subscription, created=False)

        session.refresh(subscription)
        return SubscriptionResult(subscription=subscription, created=True)


def list_subscriptions(user_id: int) -> list[Subscription]:
    # 查询用户订阅列表
    with Session(get_engine()) as session:
        return list(
            session.exec(
                select(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.enabled == True,  # noqa: E712
                )
                .order_by(Subscription.created_at)
            ).all()
        )
