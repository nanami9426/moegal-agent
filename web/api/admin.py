from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from db.models import Subscription
from db.session import get_session
from services.account.bindings import (
    get_max_bindings_per_platform,
    issue_link_code,
    list_platform_bindings,
)
from services.account.web_auth import AuthenticatedWebUser
from web.api.dependencies import require_web_user
from web.schemas import (
    AdminBindingsResponse,
    ChatHistoryResponse,
    LinkCodeResponse,
    PlatformBindingItem,
    SubscriptionItem,
    SubscriptionsResponse,
)
from web.services.accounts import (
    get_admin_visible_user,
    get_user,
    normalize_admin_platform_query,
    normalize_required_query,
)
from web.services.chat_history import build_chat_history


router = APIRouter()


@router.get(
    "/subscriptions",
    response_model=SubscriptionsResponse,
    summary="查询用户启用订阅",
    description=(
        "管理后台接口。根据 bearer token 识别当前 Web 用户，"
        "仅允许读取当前 Web 账号或已绑定 Bot 账号的启用订阅。"
    ),
)
def get_subscriptions(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
    current_user: AuthenticatedWebUser = Depends(require_web_user),
    session: Session = Depends(get_session),
) -> SubscriptionsResponse:
    platform = normalize_admin_platform_query(platform)
    platform_user_id = normalize_required_query(platform_user_id, "platform_user_id")

    user = get_admin_visible_user(session, current_user, platform, platform_user_id)
    subscriptions = session.exec(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.enabled == True,  # noqa: E712
        )
        .order_by(Subscription.created_at)
    ).all()

    return SubscriptionsResponse(
        subscriptions=[
            SubscriptionItem.model_validate(subscription)
            for subscription in subscriptions
        ]
    )


@router.get(
    "/chat-history",
    response_model=ChatHistoryResponse,
    summary="查询用户聊天历史",
    description=(
        "管理后台接口。根据 bearer token 识别当前 Web 用户，"
        "仅允许读取当前 Web 账号或已绑定 Bot 账号的会话和消息记录。"
    ),
)
def get_chat_history(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
    conversation_limit: int = Query(20, ge=1, le=100),
    message_limit: int = Query(100, ge=1, le=500),
    current_user: AuthenticatedWebUser = Depends(require_web_user),
    session: Session = Depends(get_session),
) -> ChatHistoryResponse:
    platform = normalize_admin_platform_query(platform)
    platform_user_id = normalize_required_query(platform_user_id, "platform_user_id")

    get_admin_visible_user(session, current_user, platform, platform_user_id)
    return build_chat_history(
        session,
        platform,
        platform_user_id,
        conversation_limit=conversation_limit,
        message_limit=message_limit,
    )


@router.get(
    "/admin/bindings",
    response_model=AdminBindingsResponse,
    summary="读取当前 Web 用户可查看账号",
    description="管理后台接口。返回当前 Web 账号，以及当前 Web 用户已经绑定的 TG/QQ 账号。",
)
def get_admin_bindings(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
    session: Session = Depends(get_session),
) -> AdminBindingsResponse:
    web_user = get_user(session, "web", current_user.login_id)
    if web_user is None or web_user.id != current_user.user_id:
        raise HTTPException(status_code=401, detail="Invalid web user.")

    bindings = [
        PlatformBindingItem(
            id=current_user.user_id,
            platform="web",
            platform_user_id=current_user.login_id,
            username=current_user.username,
            display_name=current_user.username,
            bound_at=web_user.created_at,
        )
    ]
    bindings.extend(
        PlatformBindingItem.model_validate(binding)
        for binding in list_platform_bindings(web_user_id=current_user.user_id)
    )

    return AdminBindingsResponse(
        bindings=bindings,
        max_per_platform=get_max_bindings_per_platform(),
    )


@router.post(
    "/admin/link-codes",
    response_model=LinkCodeResponse,
    summary="申请 Bot 账号绑定码",
    description=(
        "管理后台接口。当前 Web 用户生成 10 分钟有效绑定码；"
        "用户把绑定码发送给 TG 或 QQ bot 的 /link 命令后，即绑定对应平台账号。"
    ),
)
def create_link_code(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> LinkCodeResponse:
    try:
        link_code = issue_link_code(web_user_id=current_user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return LinkCodeResponse.model_validate(link_code)
