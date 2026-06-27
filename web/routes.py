from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session, select

from agent.router import route_message, start_new_conversation_context
from db.models import Conversation, Message, Subscription, User
from db.session import get_engine
from services.account.web_auth import (
    AuthenticatedWebUser,
    get_authenticated_web_user,
    login_web_account,
    register_web_account,
    revoke_web_session,
)
from web.schemas import (
    ChatHistoryResponse,
    ConversationHistory,
    MessageItem,
    SubscriptionItem,
    SubscriptionsResponse,
    WebAuthResponse,
    WebChatMessageRequest,
    WebChatMessageResponse,
    WebLoginRequest,
    WebMeResponse,
    WebRegisterRequest,
    WebUserItem,
)


router = APIRouter(prefix="/api")


def _normalize_required_query(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field_name} is required.")
    return normalized


def _require_web_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedWebUser:
    # Web 聊天接口使用 Bearer token；/admin 读接口按当前需求暂不鉴权。
    token = _extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.")

    user = get_authenticated_web_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return user


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@router.get(
    "/subscriptions",
    response_model=SubscriptionsResponse,
    summary="查询用户启用订阅",
    description=(
        "管理后台接口。按平台和平台用户 ID 查询已有用户的启用订阅；"
        "不会创建用户、订阅或修改任何数据。"
    ),
)
def get_subscriptions(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
) -> SubscriptionsResponse:
    # 管理后台按平台身份读取现有 Bot 用户数据，不在这里创建用户。
    platform = _normalize_required_query(platform, "platform")
    platform_user_id = _normalize_required_query(platform_user_id, "platform_user_id")

    with Session(get_engine()) as session:
        user = _get_user(session, platform, platform_user_id)
        if user is None:
            return SubscriptionsResponse(subscriptions=[])

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
        "管理后台接口。按平台和平台用户 ID 查询已有用户的会话和消息记录；"
        "支持限制返回的会话数和每个会话内的消息数。"
    ),
)
def get_chat_history(
    platform: str = Query(...),
    platform_user_id: str = Query(...),
    conversation_limit: int = Query(20, ge=1, le=100),
    message_limit: int = Query(100, ge=1, le=500),
) -> ChatHistoryResponse:
    platform = _normalize_required_query(platform, "platform")
    platform_user_id = _normalize_required_query(platform_user_id, "platform_user_id")

    with Session(get_engine()) as session:
        return _build_chat_history(
            session,
            platform,
            platform_user_id,
            conversation_limit=conversation_limit,
            message_limit=message_limit,
        )


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

    return _auth_response(result.token, result.user)


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

    return _auth_response(result.token, result.user)


@router.get(
    "/auth/me",
    response_model=WebMeResponse,
    summary="读取当前 Web 用户",
    description=(
        "读取 bearer token 对应的 Web 用户信息。用于前端刷新页面后恢复登录态。"
    ),
)
def get_me(
    current_user: AuthenticatedWebUser = Depends(_require_web_user),
) -> WebMeResponse:
    return WebMeResponse(user=_web_user_item(current_user))


@router.post(
    "/auth/logout",
    summary="退出 Web 登录",
    description="吊销当前 bearer token。即使 token 已失效，前端也可以直接清理本地登录态。",
)
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    token = _extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return {"revoked": revoke_web_session(token)}


@router.get(
    "/web-chat/history",
    response_model=ChatHistoryResponse,
    summary="查询当前 Web 用户聊天历史",
    description=(
        "Web 聊天接口。根据 bearer token 识别当前 Web 用户，返回该用户的会话和消息记录；"
        "用于聊天页刷新后恢复当前活跃会话。"
    ),
)
def get_web_chat_history(
    conversation_limit: int = Query(20, ge=1, le=100),
    message_limit: int = Query(100, ge=1, le=500),
    current_user: AuthenticatedWebUser = Depends(_require_web_user),
) -> ChatHistoryResponse:
    with Session(get_engine()) as session:
        return _build_chat_history(
            session,
            "web",
            current_user.login_id,
            conversation_limit=conversation_limit,
            message_limit=message_limit,
        )


@router.post(
    "/web-chat/messages",
    response_model=WebChatMessageResponse,
    summary="发送 Web 聊天消息",
    description=(
        "Web 聊天接口。根据 bearer token 识别当前 Web 用户，将用户消息发送给 agent，"
        "并返回最终助手回复；消息和回复会写入聊天历史。"
    ),
)
async def send_web_chat_message(
    payload: WebChatMessageRequest,
    current_user: AuthenticatedWebUser = Depends(_require_web_user),
) -> WebChatMessageResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required.")

    # Web 用户映射为 platform=web，复用现有 agent 路由、订阅工具和会话上下文。
    reply = await route_message(
        "web",
        current_user.login_id,
        message,
        username=current_user.username,
        display_name=current_user.username,
    )
    return WebChatMessageResponse(reply=reply)


@router.post(
    "/web-chat/new",
    summary="开启新的 Web 聊天会话",
    description=(
        "Web 聊天接口。结束当前 Web 用户的活跃会话，并创建新的聊天上下文；"
        "不会删除历史会话、订阅或摘要记录。"
    ),
)
def start_new_web_chat(
    current_user: AuthenticatedWebUser = Depends(_require_web_user),
) -> dict[str, bool]:
    start_new_conversation_context(
        "web",
        current_user.login_id,
        username=current_user.username,
        display_name=current_user.username,
    )
    return {"created": True}


def _get_user(
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


def _build_chat_history(
    session: Session,
    platform: str,
    platform_user_id: str,
    *,
    conversation_limit: int,
    message_limit: int,
) -> ChatHistoryResponse:
    # 后台查询和 Web 聊天历史共用同一段组装逻辑，避免返回结构漂移。
    user = _get_user(session, platform, platform_user_id)
    if user is None:
        return ChatHistoryResponse(conversations=[])

    conversations = session.exec(
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.platform == platform,
            Conversation.platform_user_id == platform_user_id,
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(conversation_limit)
    ).all()

    conversation_history = []
    for conversation in conversations:
        messages = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
            .limit(message_limit)
        ).all()
        conversation_history.append(
            ConversationHistory(
                id=conversation.id,
                version=conversation.version,
                is_active=conversation.is_active,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                ended_at=conversation.ended_at,
                messages=[
                    MessageItem.model_validate(message)
                    for message in messages
                ],
            )
        )

    return ChatHistoryResponse(conversations=conversation_history)


def _auth_response(token: str, user: AuthenticatedWebUser) -> WebAuthResponse:
    return WebAuthResponse(token=token, user=_web_user_item(user))


def _web_user_item(user: AuthenticatedWebUser) -> WebUserItem:
    return WebUserItem(
        id=user.user_id,
        username=user.username,
    )
