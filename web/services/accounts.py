from fastapi import HTTPException
from sqlmodel import Session, select

from db.models import User, WebBotBinding
from services.account.bindings import normalize_bot_platform
from services.account.web_auth import AuthenticatedWebUser


def normalize_required_query(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field_name} is required.")
    return normalized


def normalize_admin_platform_query(platform: str) -> str:
    normalized = normalize_required_query(platform, "platform").lower()
    if normalized == "web":
        return normalized

    try:
        return normalize_bot_platform(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def get_user(
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


def get_admin_visible_user(
    session: Session,
    current_user: AuthenticatedWebUser,
    platform: str,
    platform_user_id: str,
) -> User:
    if platform == "web":
        if platform_user_id != current_user.login_id:
            raise HTTPException(status_code=403, detail="只能查看当前 Web 用户的数据。")
        user = get_user(session, "web", current_user.login_id)
        if user is None or user.id != current_user.user_id:
            raise HTTPException(status_code=403, detail="只能查看当前 Web 用户的数据。")
        return user

    return get_bound_bot_user(session, current_user, platform, platform_user_id)


def get_bound_bot_user(
    session: Session,
    current_user: AuthenticatedWebUser,
    platform: str,
    platform_user_id: str,
) -> User:
    user = get_user(session, platform, platform_user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="请先绑定该平台账号。")

    binding = session.exec(
        select(WebBotBinding).where(
            WebBotBinding.web_user_id == current_user.user_id,
            WebBotBinding.bot_user_id == user.id,
            WebBotBinding.platform == platform,
            WebBotBinding.platform_user_id == platform_user_id,
        )
    ).first()
    if binding is None:
        raise HTTPException(status_code=403, detail="请先绑定该平台账号。")

    return user
