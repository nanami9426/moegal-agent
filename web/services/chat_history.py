from sqlmodel import Session, select

from db.models import Conversation, Message
from web.schemas import ChatHistoryResponse, ConversationHistory, MessageItem
from web.services.accounts import get_user


def build_chat_history(
    session: Session,
    platform: str,
    platform_user_id: str,
    *,
    conversation_limit: int,
    message_limit: int,
) -> ChatHistoryResponse:
    user = get_user(session, platform, platform_user_id)
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
