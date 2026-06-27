from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from db.models import Conversation, Message, Subscription, User
from db.session import get_engine
from web.schemas import (
    ChatHistoryResponse,
    ConversationHistory,
    MessageItem,
    SubscriptionItem,
    SubscriptionsResponse,
)


router = APIRouter(prefix="/api")


def _normalize_required_query(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field_name} is required.")
    return normalized


@router.get("/subscriptions", response_model=SubscriptionsResponse)
def get_subscriptions(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
) -> SubscriptionsResponse:
    platform = _normalize_required_query(platform, "platform")
    platform_user_id = _normalize_required_query(platform_user_id, "platform_user_id")

    with Session(get_engine()) as session:
        user = _get_user(session, platform, platform_user_id)
        if user is None:
            return SubscriptionsResponse(subscriptions=[])

        subscriptions = session.exec(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.enabled == True,  # noqa: E712
            )
            .order_by(Subscription.created_at)
        ).all()

        return SubscriptionsResponse(
            subscriptions=[
                SubscriptionItem.model_validate(subscription)
                for subscription in subscriptions
            ]
        )


@router.get("/chat-history", response_model=ChatHistoryResponse)
def get_chat_history(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
    conversation_limit: int = Query(20, ge=1, le=100),
    message_limit: int = Query(100, ge=1, le=500),
) -> ChatHistoryResponse:
    platform = _normalize_required_query(platform, "platform")
    platform_user_id = _normalize_required_query(platform_user_id, "platform_user_id")

    with Session(get_engine()) as session:
        user = _get_user(session, platform, platform_user_id)
        if user is None:
            return ChatHistoryResponse(conversations=[])

        conversations = session.exec(
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.platform == platform,
                Conversation.platform_user_id == platform_user_id,
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(conversation_limit)
        ).all()

        conversation_history = []
        for conversation in conversations:
            messages = session.exec(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at, Message.id)
                .limit(message_limit)
            ).all()
            conversation_history.append(
                ConversationHistory(
                    id=conversation.id,
                    version=conversation.version,
                    is_active=conversation.is_active,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                    ended_at=conversation.ended_at,
                    messages=[
                        MessageItem.model_validate(message)
                        for message in messages
                    ],
                )
            )

        return ChatHistoryResponse(conversations=conversation_history)


def _get_user(
    session: Session,
    platform: str,
    platform_user_id: str,
) -> User | None:
    return session.exec(
        select(User).where(
            User.platform == platform,
            User.platform_user_id == platform_user_id,
        )
    ).first()

