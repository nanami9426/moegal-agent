from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import User, utc_now
from db.session import get_engine


@dataclass(frozen=True)
class UserProfile:
    platform: str
    platform_user_id: str
    username: str | None = None
    display_name: str | None = None
    language_code: str | None = None
    timezone: str | None = None


def upsert_user(platform: str, platform_user_id: str,
    *,
    username: str | None = None, display_name: str | None = None,
    language_code: str | None = None, timezone: str | None = None,
) -> User:
    profile = UserProfile(
        platform=platform.strip(),
        platform_user_id=str(platform_user_id).strip(),
        username=username,
        display_name=display_name,
        language_code=language_code,
        timezone=timezone,
    )

    if not profile.platform or not profile.platform_user_id:
        raise ValueError("platform and platform_user_id are required.")

    with Session(get_engine()) as session:
        user = session.exec(
            select(User).where(
                User.platform == profile.platform,
                User.platform_user_id == profile.platform_user_id,
            )
        ).first()

        now = utc_now()
        if user is None:
            user = User(
                platform=profile.platform,
                platform_user_id=profile.platform_user_id,
                username=profile.username,
                display_name=profile.display_name,
                language_code=profile.language_code,
                timezone=profile.timezone,
                last_seen_at=now,
            )
            session.add(user)
        else:
            if profile.username is not None:
                user.username = profile.username
            if profile.display_name is not None:
                user.display_name = profile.display_name
            if profile.language_code is not None:
                user.language_code = profile.language_code
            if profile.timezone is not None:
                user.timezone = profile.timezone
            user.last_seen_at = now
            user.updated_at = now

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            user = session.exec(
                select(User).where(
                    User.platform == profile.platform,
                    User.platform_user_id == profile.platform_user_id,
                )
            ).one()

        session.refresh(user)
        return user
