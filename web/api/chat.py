import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from agent.router import (
    route_message,
    route_message_stream,
    start_new_conversation_context,
)
from db.session import get_session
from services.account.web_auth import AuthenticatedWebUser
from services.account.memories import (
    clear_memory_document,
    get_memory_document,
    get_memory_settings,
    update_memory_document,
    update_memory_settings,
)
from web.api.dependencies import require_web_user
from web.schemas import (
    ChatHistoryResponse,
    MemoryDocumentItem,
    MemoryDocumentUpdateRequest,
    MemorySettingsItem,
    MemorySettingsUpdateRequest,
    WebChatMessageRequest,
    WebChatMessageResponse,
)
from web.services.chat_history import build_chat_history


router = APIRouter()


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
    current_user: AuthenticatedWebUser = Depends(require_web_user),
    session: Session = Depends(get_session),
) -> ChatHistoryResponse:
    return build_chat_history(
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
    current_user: AuthenticatedWebUser = Depends(require_web_user),
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
        temporary=payload.temporary,
        temporary_thread_id=payload.temporary_thread_id,
    )
    return WebChatMessageResponse(reply=reply)


@router.post(
    "/web-chat/messages/stream",
    summary="流式发送 Web 聊天消息",
    description=(
        "Web 聊天接口。根据 bearer token 识别当前 Web 用户，用 text/event-stream "
        "逐步返回助手回复；消息和最终回复会写入聊天历史。"
    ),
)
async def stream_web_chat_message(
    payload: WebChatMessageRequest,
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> StreamingResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required.")

    async def event_stream() -> AsyncIterator[str]:
        reply_parts: list[str] = []
        try:
            async for chunk in route_message_stream(
                "web",
                current_user.login_id,
                message,
                username=current_user.username,
                display_name=current_user.username,
                temporary=payload.temporary,
                temporary_thread_id=payload.temporary_thread_id,
            ):
                reply_parts.append(chunk)
                data = json.dumps(
                    {"delta": chunk},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"data: {data}\n\n"
            data = json.dumps(
                {"reply": "".join(reply_parts)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: done\ndata: {data}\n\n"
        except Exception as exc:
            # 流式响应头已发出，后续错误只能通过 SSE 事件告诉前端。
            data = json.dumps(
                {"detail": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/web-chat/new",
    summary="开启新的 Web 聊天会话",
    description=(
        "Web 聊天接口。结束当前 Web 用户的活跃会话，并创建新的聊天上下文；"
        "不会删除历史会话、订阅或长期记忆。"
    ),
)
def start_new_web_chat(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> dict[str, bool | str]:
    result = start_new_conversation_context(
        "web",
        current_user.login_id,
        username=current_user.username,
        display_name=current_user.username,
    )
    if result.created:
        return {"created": True, "message": "已开启新的对话。"}
    return {"created": False, "message": "已在新对话中。"}


@router.get(
    "/web-chat/memory",
    response_model=MemoryDocumentItem,
    summary="查看当前用户 Markdown 长期记忆",
)
def get_web_chat_memory(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> MemoryDocumentItem:
    return MemoryDocumentItem.model_validate(
        get_memory_document(current_user.user_id)
    )


@router.patch(
    "/web-chat/memory",
    response_model=MemoryDocumentItem,
    summary="替换当前用户 Markdown 长期记忆",
)
def patch_web_chat_memory_document(
    payload: MemoryDocumentUpdateRequest,
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> MemoryDocumentItem:
    try:
        document = update_memory_document(current_user.user_id, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MemoryDocumentItem.model_validate(document)


@router.delete(
    "/web-chat/memory",
    response_model=MemoryDocumentItem,
    summary="清空当前用户 Markdown 长期记忆",
)
def clear_web_chat_memory(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> MemoryDocumentItem:
    return MemoryDocumentItem.model_validate(
        clear_memory_document(current_user.user_id)
    )


@router.get(
    "/web-chat/memory-settings",
    response_model=MemorySettingsItem,
    summary="读取当前用户记忆设置",
)
def get_web_chat_memory_settings(
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> MemorySettingsItem:
    return MemorySettingsItem.model_validate(get_memory_settings(current_user.user_id))


@router.patch(
    "/web-chat/memory-settings",
    response_model=MemorySettingsItem,
    summary="修改当前用户记忆设置",
)
def patch_web_chat_memory_settings(
    payload: MemorySettingsUpdateRequest,
    current_user: AuthenticatedWebUser = Depends(require_web_user),
) -> MemorySettingsItem:
    settings = update_memory_settings(
        current_user.user_id,
        enabled=payload.enabled,
        auto_extract=payload.auto_extract,
    )
    return MemorySettingsItem.model_validate(settings)
