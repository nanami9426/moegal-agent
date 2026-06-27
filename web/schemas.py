from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubscriptionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    target: str
    display_name: str | None
    delivery_mode: str
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None


class SubscriptionsResponse(BaseModel):
    subscriptions: list[SubscriptionItem]


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str | None
    created_at: datetime


class ConversationHistory(BaseModel):
    id: int
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    messages: list[MessageItem]


class ChatHistoryResponse(BaseModel):
    conversations: list[ConversationHistory]

