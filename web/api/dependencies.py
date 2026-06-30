from fastapi import Header, HTTPException

from services.account.web_auth import AuthenticatedWebUser, get_authenticated_web_user


def extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_web_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedWebUser:
    # Web 账号接口统一使用 Bearer token，后续路由再按绑定关系做数据隔离。
    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.")

    user = get_authenticated_web_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return user
