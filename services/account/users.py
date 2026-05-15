from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import User, utc_now
from db.session import get_engine

MAX_USER_ID_CREATE_ATTEMPTS = 3


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
        user = _get_user_by_platform(session, profile)

        now = utc_now()
        if user is not None:
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

            session.commit()
            session.refresh(user)
            return user

        last_error: IntegrityError | None = None
        for _ in range(MAX_USER_ID_CREATE_ATTEMPTS):
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

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                existing_user = _get_user_by_platform(session, profile)
                if existing_user is not None:
                    return existing_user
                last_error = exc
                continue

            session.refresh(user)
            return user

        raise RuntimeError(
            "Could not generate a unique 10-digit user id after "
            f"{MAX_USER_ID_CREATE_ATTEMPTS} attempts."
        ) from last_error


def _get_user_by_platform(session: Session, profile: UserProfile) -> User | None:
    return session.exec(
        select(User).where(
            User.platform == profile.platform,
            User.platform_user_id == profile.platform_user_id,
        )
    ).first()
