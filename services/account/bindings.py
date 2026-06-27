import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from db.models import User, WebBotBinding, WebLinkCode, utc_now
from db.session import get_engine


SUPPORTED_BOT_PLATFORMS = frozenset({"tg", "qq"})
LINK_CODE_TTL = timedelta(minutes=10)
LINK_CODE_LENGTH = 8
LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_BINDINGS_ENV = "MOEGAL_MAX_LINKED_BOT_USERS_PER_PLATFORM"
DEFAULT_MAX_BINDINGS_PER_PLATFORM = 2


@dataclass(frozen=True)
class PlatformBinding:
    id: int
    platform: str
    platform_user_id: str
    username: str | None
    display_name: str | None
    bound_at: datetime


@dataclass(frozen=True)
class LinkCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class CompleteLinkResult:
    binding: PlatformBinding
    already_bound: bool


def get_max_bindings_per_platform() -> int:
    raw_value = (os.getenv(MAX_BINDINGS_ENV) or "").strip()
    if not raw_value:
        return DEFAULT_MAX_BINDINGS_PER_PLATFORM

    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_BINDINGS_PER_PLATFORM

    return max(1, value)


def issue_link_code(*, web_user_id: int) -> LinkCode:
    now = utc_now()

    with Session(get_engine()) as session:
        web_user = session.get(User, web_user_id)
        if web_user is None or web_user.platform != "web":
            raise ValueError("Web 用户不存在。")

        # 同一 Web 用户只保留最新绑定码，减少用户误用旧码的机会。
        active_codes = session.exec(
            select(WebLinkCode).where(
                WebLinkCode.web_user_id == web_user_id,
                WebLinkCode.used_at.is_(None),
                WebLinkCode.expires_at > now,
            )
        ).all()
        for active_code in active_codes:
            active_code.expires_at = now
            session.add(active_code)

        code = _generate_link_code()
        expires_at = now + LINK_CODE_TTL
        session.add(
            WebLinkCode(
                web_user_id=web_user_id,
                code_hash=_hash_code(code),
                created_at=now,
                expires_at=expires_at,
            )
        )
        session.commit()

    return LinkCode(code=code, expires_at=expires_at)


def list_platform_bindings(*, web_user_id: int) -> list[PlatformBinding]:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(WebBotBinding, User)
            .join(User, WebBotBinding.bot_user_id == User.id)
            .where(WebBotBinding.web_user_id == web_user_id)
            .order_by(WebBotBinding.platform, WebBotBinding.created_at)
        ).all()

    return [
        _binding_item(binding, bot_user)
        for binding, bot_user in rows
    ]


def complete_platform_link(
    *,
    platform: str,
    platform_user_id: str,
    code: str,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
) -> CompleteLinkResult:
    platform = normalize_bot_platform(platform)
    platform_user_id = str(platform_user_id).strip()
    if not platform_user_id:
        raise ValueError("无法识别当前 Bot 用户。")

    normalized_code = _normalize_code(code)
    if not normalized_code:
        raise ValueError("绑定码不能为空。")

    with Session(get_engine()) as session:
        now = utc_now()
        link_code = session.exec(
            select(WebLinkCode).where(
                WebLinkCode.code_hash == _hash_code(normalized_code),
                WebLinkCode.used_at.is_(None),
                WebLinkCode.expires_at > now,
            )
        ).first()
        if link_code is None:
            raise ValueError("绑定码无效或已过期。")

        web_user = session.get(User, link_code.web_user_id)
        if web_user is None or web_user.platform != "web":
            raise ValueError("绑定码对应的 Web 用户不存在。")

        bot_user = _upsert_bot_user(
            session,
            platform=platform,
            platform_user_id=platform_user_id,
            username=username,
            display_name=display_name,
            language_code=language_code,
            now=now,
        )

        existing_binding = session.exec(
            select(WebBotBinding).where(WebBotBinding.bot_user_id == bot_user.id)
        ).first()
        if existing_binding is not None:
            if existing_binding.web_user_id != web_user.id:
                raise ValueError("该 Bot 账号已经绑定其他 Web 用户。")

            link_code.used_at = now
            session.add(link_code)
            session.commit()
            return CompleteLinkResult(
                binding=_binding_item(existing_binding, bot_user),
                already_bound=True,
            )

        current_count = _count_platform_bindings(
            session,
            web_user_id=web_user.id,
            platform=platform,
        )
        max_count = get_max_bindings_per_platform()
        if current_count >= max_count:
            raise ValueError(
                f"每个 Web 用户最多绑定 {max_count} 个 {_platform_label(platform)} 账号。"
            )

        binding = WebBotBinding(
            web_user_id=web_user.id,
            bot_user_id=bot_user.id,
            platform=platform,
            platform_user_id=platform_user_id,
            created_at=now,
        )
        link_code.used_at = now
        session.add(binding)
        session.add(link_code)
        session.commit()
        session.refresh(binding)
        session.refresh(bot_user)

        return CompleteLinkResult(
            binding=_binding_item(binding, bot_user),
            already_bound=False,
        )


def normalize_bot_platform(platform: str) -> str:
    normalized = platform.strip().lower()
    if normalized not in SUPPORTED_BOT_PLATFORMS:
        raise ValueError("仅支持绑定 Telegram 或 QQ。")
    return normalized


def _count_platform_bindings(session: Session, *, web_user_id: int, platform: str) -> int:
    return int(
        session.exec(
            select(func.count(WebBotBinding.id)).where(
                WebBotBinding.web_user_id == web_user_id,
                WebBotBinding.platform == platform,
            )
        ).one()
    )


def _upsert_bot_user(
    session: Session,
    *,
    platform: str,
    platform_user_id: str,
    username: str | None,
    display_name: str | None,
    language_code: str | None,
    now: datetime,
) -> User:
    user = session.exec(
        select(User).where(
            User.platform == platform,
            User.platform_user_id == platform_user_id,
        )
    ).first()
    if user is None:
        user = User(
            platform=platform,
            platform_user_id=platform_user_id,
            username=username,
            display_name=display_name,
            language_code=language_code,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
    else:
        if username is not None:
            user.username = username
        if display_name is not None:
            user.display_name = display_name
        if language_code is not None:
            user.language_code = language_code
        user.last_seen_at = now
        user.updated_at = now

    session.add(user)
    session.flush()
    return user


def _binding_item(binding: WebBotBinding, bot_user: User) -> PlatformBinding:
    if binding.id is None:
        raise RuntimeError("Binding has not been persisted.")

    return PlatformBinding(
        id=binding.id,
        platform=binding.platform,
        platform_user_id=binding.platform_user_id,
        username=bot_user.username,
        display_name=bot_user.display_name,
        bound_at=binding.created_at,
    )


def _generate_link_code() -> str:
    return "".join(secrets.choice(LINK_CODE_ALPHABET) for _ in range(LINK_CODE_LENGTH))


def _normalize_code(code: str) -> str:
    return code.strip().replace(" ", "").replace("-", "").upper()


def _hash_code(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode("utf-8")).hexdigest()


def _platform_label(platform: str) -> str:
    return "Telegram" if platform == "tg" else "QQ"
