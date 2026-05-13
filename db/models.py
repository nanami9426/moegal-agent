from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_users_platform_user"),
    )

    id: int | None = Field(default=None, primary_key=True)
    platform: str = Field(index=True, max_length=32)
    platform_user_id: str = Field(index=True, max_length=128)
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    language_code: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    last_seen_at: datetime | None = Field(default=None)


class Subscription(SQLModel, table=True):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "target", name="uq_subscriptions_user_target"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    type: str = Field(index=True, max_length=64)
    target: str = Field(max_length=512)
    display_name: str | None = Field(default=None, max_length=255)
    enabled: bool = Field(default=True, nullable=False)
    # JSON 字段用于保存订阅过滤规则，方便后续扩展不同平台的条件。
    filters: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    delivery_mode: str = Field(default="daily", max_length=32)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    last_checked_at: datetime | None = Field(default=None)


class ContentItem(SQLModel, table=True):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_content_items_source"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_type: str = Field(index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    summary: str | None = Field(default=None)
    author: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = Field(default=None, index=True)
    fetched_at: datetime = Field(default_factory=utc_now, nullable=False)
    # 保存原始抓取结果，避免早期频繁调整表结构。
    raw: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    hash: str | None = Field(default=None, index=True, max_length=128)


class Delivery(SQLModel, table=True):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("user_id", "content_item_id", name="uq_deliveries_user_content"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    subscription_id: int | None = Field(
        default=None,
        foreign_key="subscriptions.id",
        index=True,
    )
    content_item_id: int = Field(foreign_key="content_items.id", index=True)
    status: str = Field(default="pending", index=True, max_length=32)
    sent_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class MediaAsset(SQLModel, table=True):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("platform", "platform_unique_id", name="uq_media_assets_platform_unique"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    platform: str = Field(index=True, max_length=32)
    platform_file_id: str = Field(max_length=255)
    platform_unique_id: str = Field(index=True, max_length=255)
    file_path: str = Field(max_length=2048)
    mime_type: str | None = Field(default=None, max_length=128)
    sha256: str | None = Field(default=None, index=True, max_length=64)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    caption: str | None = Field(default=None)
    # 后续 vision 模型、搜图结果、标签都放这里。
    analysis: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    platform: str = Field(index=True, max_length=32)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str = Field(index=True, max_length=32)
    content: str | None = Field(default=None)
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
