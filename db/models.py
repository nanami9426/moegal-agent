import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, ForeignKey, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_user_id() -> int:
    return secrets.randbelow(9_000_000_000) + 1_000_000_000


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_users_platform_user"),
    )

    id: int = Field(
        default_factory=generate_user_id,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=False),
    )
    platform: str = Field(index=True, max_length=32)
    platform_user_id: str = Field(index=True, max_length=128)
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    language_code: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    last_seen_at: datetime | None = Field(default=None)


# Web 登录信息单独存放；业务身份仍落到 users，使用 platform=web 复用订阅和会话。
class WebAccount(SQLModel, table=True):
    __tablename__ = "web_accounts"
    __table_args__ = (
        UniqueConstraint("login_id", name="uq_web_accounts_login_id"),
        UniqueConstraint("user_id", name="uq_web_accounts_user_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    login_id: str = Field(index=True, max_length=10)
    username: str = Field(max_length=64)
    password_hash: str = Field(max_length=512, nullable=False)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


# Web 会话只保存 token 哈希值，明文 token 只在登录/注册响应中返回给前端。
class WebSession(SQLModel, table=True):
    __tablename__ = "web_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_web_sessions_token_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    token_hash: str = Field(index=True, max_length=128)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    expires_at: datetime = Field(nullable=False)
    revoked_at: datetime | None = Field(default=None)


class WebLinkCode(SQLModel, table=True):
    __tablename__ = "web_link_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_web_link_codes_code_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    web_user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    # 只保存绑定码哈希，避免数据库泄露后 10 分钟内的明文码可被直接使用。
    code_hash: str = Field(index=True, max_length=128)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    expires_at: datetime = Field(nullable=False)
    used_at: datetime | None = Field(default=None)


class WebBotBinding(SQLModel, table=True):
    __tablename__ = "web_bot_bindings"
    __table_args__ = (
        UniqueConstraint(
            "web_user_id",
            "platform",
            "platform_user_id",
            name="uq_web_bot_bindings_web_platform_user",
        ),
        UniqueConstraint("bot_user_id", name="uq_web_bot_bindings_bot_user"),
    )

    id: int | None = Field(default=None, primary_key=True)
    web_user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    bot_user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    platform: str = Field(index=True, max_length=32)
    platform_user_id: str = Field(index=True, max_length=128)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class Subscription(SQLModel, table=True):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "target", name="uq_subscriptions_user_target"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
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
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
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
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
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
    __table_args__ = (
        # thread_id 直接对应 LangGraph checkpoint 的会话隔离键，新会话使用随机 UUID。
        UniqueConstraint("thread_id", name="uq_conversations_thread_id"),
        # 同一平台用户的每个对话版本只允许存在一条记录。
        UniqueConstraint(
            "platform",
            "platform_user_id",
            "version",
            name="uq_conversations_platform_user_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("users.id"), index=True, nullable=False),
    )
    platform: str = Field(index=True, max_length=32)
    platform_user_id: str = Field(index=True, max_length=128)
    thread_id: str = Field(index=True, max_length=255)
    # version 只做业务会话序号；实际 checkpoint 隔离依赖 UUID thread_id。
    version: int = Field(default=0, index=True, nullable=False)
    is_active: bool = Field(default=True, index=True, nullable=False)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    ended_at: datetime | None = Field(default=None)


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
