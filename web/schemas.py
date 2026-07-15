from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class TokenUsageSummary(BaseModel):
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    average_elapsed_ms: int
    latest_created_at: datetime | None


class TokenUsageByModelItem(BaseModel):
    model: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TokenUsageRecordItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model: str
    request_path: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    status_code: int
    elapsed_ms: int
    created_at: datetime


class TokenUsageResponse(BaseModel):
    summary: TokenUsageSummary
    by_model: list[TokenUsageByModelItem]
    recent: list[TokenUsageRecordItem]


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
    temporary: bool = False
    temporary_thread_id: str | None = Field(default=None, max_length=128)


class WebChatMessageResponse(BaseModel):
    reply: str


class MemoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    namespace: str
    kind: str
    key: str
    content: str
    source: str
    confidence: float
    importance: float
    expires_at: datetime | None
    last_accessed_at: datetime | None
    access_count: int
    created_at: datetime
    updated_at: datetime


class MemoriesResponse(BaseModel):
    memories: list[MemoryItem]


class MemoryUpdateRequest(BaseModel):
    content: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    expires_at: datetime | None = None


class MemorySettingsItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    auto_extract: bool
    use_chat_history: bool
    updated_at: datetime


class MemorySettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    auto_extract: bool | None = None
    use_chat_history: bool | None = None
