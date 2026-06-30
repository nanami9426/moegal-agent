from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from db.session import get_session
from services.account.web_auth import AuthenticatedWebUser
from web.api.dependencies import require_web_user
from web.schemas import TokenUsageResponse
from web.services.accounts import (
    get_admin_visible_user,
    normalize_admin_platform_query,
    normalize_required_query,
)
from web.services.token_usage import build_token_usage


router = APIRouter()


@router.get(
    "/token-usage",
    response_model=TokenUsageResponse,
    summary="查询用户 LLM token 用量",
    description=(
        "管理后台接口。根据 bearer token 识别当前 Web 用户，"
        "仅允许读取当前 Web 账号或已绑定 Bot 账号的 LLM token 用量。"
    ),
)
def get_token_usage(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
    recent_limit: int = Query(20, ge=1, le=100),
    current_user: AuthenticatedWebUser = Depends(require_web_user),
    session: Session = Depends(get_session),
) -> TokenUsageResponse:
    platform = normalize_admin_platform_query(platform)
    platform_user_id = normalize_required_query(platform_user_id, "platform_user_id")

    user = get_admin_visible_user(session, current_user, platform, platform_user_id)
    return build_token_usage(session, user.id, recent_limit=recent_limit)
