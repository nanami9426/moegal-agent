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


class PlatformBindingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    platform_user_id: str
    username: str | None
    display_name: str | None
    bound_at: datetime


class AdminBindingsResponse(BaseModel):
    bindings: list[PlatformBindingItem]
    max_per_platform: int


class LinkCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    expires_at: datetime


class WebUserItem(BaseModel):
    id: int
    username: str


class WebRegisterRequest(BaseModel):
    username: str
    password: str


class WebLoginRequest(BaseModel):
    user_id: str
    password: str


class WebAuthResponse(BaseModel):
    token: str
    user: WebUserItem


class WebMeResponse(BaseModel):
    user: WebUserItem


class WebChatMessageRequest(BaseModel):
    message: str


class WebChatMessageResponse(BaseModel):
    reply: str
