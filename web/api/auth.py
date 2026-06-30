from fastapi import APIRouter, Depends, Header, HTTPException

from services.account.web_auth import (
    AuthenticatedWebUser,
    login_web_account,
    register_web_account,
    revoke_web_session,
)
from web.api.dependencies import extract_bearer_token, require_web_user
from web.schemas import (
    WebAuthResponse,
    WebLoginRequest,
    WebMeResponse,
    WebRegisterRequest,
)


router = APIRouter()


@router.post(
    "/auth/register",
    response_model=WebAuthResponse,
    summary="注册 Web 用户",
    description=(
        "Web 端账号注册接口。用户提交用户名和密码，平台分配 10 位纯数字用户 ID，"
        "并返回登录 token 和用户信息。"
    ),
)
def register(payload: WebRegisterRequest) -> WebAuthResponse:
    try:
        result = register_web_account(
            username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return WebAuthResponse(
        token=result.token,
        user={"id": result.user.user_id, "username": result.user.username},
    )


@router.post(
    "/auth/login",
    response_model=WebAuthResponse,
    summary="登录 Web 用户",
    description=(
        "Web 端账号登录接口。用户使用平台注册时分配的 10 位用户 ID 和密码登录，"
        "登录成功后返回 bearer token 和用户信息。"
    ),
)
def login(payload: WebLoginRequest) -> WebAuthResponse:
    try:
        result = login_web_account(
            user_id=payload.user_id,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return WebAuthResponse(
        token=result.token,
        user={"id": result.user.user_id, "username": result.user.username},
    )


@router.get(
    "/auth/me",
    response_model=WebMeResponse,
    summary="读取当前 Web 用户",
    description=(
        "读取 bearer token 对应的 Web 用户信息。用于前端刷新页面后恢复登录态。"
    ),
)
def get_me(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> WebMeResponse:
    return WebMeResponse(
        user={"id": current_user.user_id, "username": current_user.username}
    )


@router.post(
    "/auth/logout",
    summary="退出 Web 登录",
    description="吊销当前 bearer token。即使 token 已失效，前端也可以直接清理本地登录态。",
)
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return {"revoked": revoke_web_session(token)}
