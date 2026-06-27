import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import User, WebAccount, WebSession, utc_now
from db.session import get_engine


SESSION_TTL = timedelta(days=30)
PASSWORD_ITERATIONS = 260_000
PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
USER_ID_PATTERN = re.compile(r"^\d{10}$")
MAX_ACCOUNT_CREATE_ATTEMPTS = 3
MAX_USERNAME_LENGTH = 64


@dataclass(frozen=True)
class AuthenticatedWebUser:
    user_id: int
    login_id: str
    username: str


@dataclass(frozen=True)
class WebAuthResult:
    token: str
    user: AuthenticatedWebUser


def register_web_account(*, username: str, password: str) -> WebAuthResult:
    # 用户注册时取用户名并设置密码；平台生成 users.id 作为 10 位登录 ID。
    normalized_username = _normalize_username(username)
    _validate_password(password)

    with Session(get_engine()) as session:
        last_error: IntegrityError | None = None
        for _ in range(MAX_ACCOUNT_CREATE_ATTEMPTS):
            now = utc_now()
            user = User(
                platform="web",
                platform_user_id="",
                username=normalized_username,
                display_name=normalized_username,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            login_id = str(user.id)
            user.platform_user_id = login_id
            session.add(user)

            account = WebAccount(
                user_id=user.id,
                login_id=login_id,
                username=normalized_username,
                password_hash=_hash_password(password),
                created_at=now,
                updated_at=now,
            )
            session.add(account)
            token = _add_session(session, user.id, now=now)

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                last_error = exc
                continue

            return WebAuthResult(
                token=token,
                user=AuthenticatedWebUser(
                    user_id=user.id,
                    login_id=login_id,
                    username=account.username,
                ),
            )

        raise RuntimeError("Could not create web account.") from last_error


def login_web_account(*, user_id: str, password: str) -> WebAuthResult:
    login_id = _normalize_login_id(user_id)

    with Session(get_engine()) as session:
        # 登录使用平台分配的 10 位 ID，再用用户注册时设置的密码校验身份。
        account = _get_account_by_login_id(session, login_id)
        if account is None or not _verify_password(password, account.password_hash):
            raise ValueError("用户 ID 或密码错误。")

        user = session.get(User, account.user_id)
        if user is None or user.platform != "web" or user.platform_user_id != login_id:
            raise ValueError("用户 ID 或密码错误。")

        now = utc_now()
        user.username = account.username
        user.display_name = account.username
        user.last_seen_at = now
        user.updated_at = now
        session.add(user)
        token = _add_session(session, user.id, now=now)
        session.commit()

        return WebAuthResult(
            token=token,
            user=AuthenticatedWebUser(
                user_id=user.id,
                login_id=login_id,
                username=account.username,
            ),
        )


def get_authenticated_web_user(token: str) -> AuthenticatedWebUser | None:
    token = token.strip()
    if not token:
        return None

    with Session(get_engine()) as session:
        now = utc_now()
        # Bearer token 明文不落库，只用 SHA-256 哈希做查找和吊销。
        web_session = session.exec(
            select(WebSession).where(
                WebSession.token_hash == _hash_token(token),
                WebSession.revoked_at.is_(None),
                WebSession.expires_at > now,
            )
        ).first()
        if web_session is None:
            return None

        account = session.exec(
            select(WebAccount).where(WebAccount.user_id == web_session.user_id)
        ).first()
        if account is None:
            return None

        return AuthenticatedWebUser(
            user_id=web_session.user_id,
            login_id=account.login_id,
            username=account.username,
        )


def revoke_web_session(token: str) -> bool:
    token = token.strip()
    if not token:
        return False

    with Session(get_engine()) as session:
        web_session = session.exec(
            select(WebSession).where(
                WebSession.token_hash == _hash_token(token),
                WebSession.revoked_at.is_(None),
            )
        ).first()
        if web_session is None:
            return False

        web_session.revoked_at = utc_now()
        session.add(web_session)
        session.commit()
        return True


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise ValueError("用户名不能为空。")
    if len(normalized) > MAX_USERNAME_LENGTH:
        raise ValueError(f"用户名不能超过 {MAX_USERNAME_LENGTH} 个字符。")
    return normalized


def _normalize_login_id(user_id: str) -> str:
    normalized = str(user_id).strip()
    if not USER_ID_PATTERN.fullmatch(normalized):
        raise ValueError("用户 ID 必须是 10 位纯数字。")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 6:
        raise ValueError("密码至少需要 6 位。")
    if len(password) > 256:
        raise ValueError("密码过长。")


def _hash_password(password: str) -> str:
    # 使用标准库 PBKDF2 + 随机盐，避免为早期简单账号体系引入额外依赖。
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_HASH_PREFIX}${PASSWORD_ITERATIONS}${salt}${encoded_digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        prefix, iterations, salt, expected_digest = password_hash.split("$", 3)
        iteration_count = int(iterations)
    except ValueError:
        return False

    if prefix != PASSWORD_HASH_PREFIX:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iteration_count,
    )
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return hmac.compare_digest(encoded_digest, expected_digest)


def _add_session(session: Session, user_id: int, *, now) -> str:
    # token 明文只返回给客户端；服务端保存哈希和过期时间。
    token = secrets.token_urlsafe(32)
    session.add(
        WebSession(
            user_id=user_id,
            token_hash=_hash_token(token),
            created_at=now,
            expires_at=now + SESSION_TTL,
        )
    )
    return token


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_account_by_login_id(session: Session, login_id: str) -> WebAccount | None:
    return session.exec(
        select(WebAccount).where(WebAccount.login_id == login_id)
    ).first()
