import asyncio
import base64
from dataclasses import dataclass
from typing import Literal

from agent.router import classify_image_translation_intent, route_image_message
from services.manga_translate.translate import (
    TranslateInputError,
    is_manga_image_bytes,
    translate_image_bytes,
)
from services.account.users import upsert_user
from utils.logger import logger


ASK_TRANSLATE_MESSAGE = "这张图需要我帮你翻译吗？"
IMAGE_PROCESS_FAILED_MESSAGE = "图片处理失败，请稍后再试。"
IMAGE_UNDERSTANDING_FAILED_MESSAGE = "图片理解失败，请稍后再试。"
NO_TEXT_DETECTED_MESSAGE = "未检测出文字"

ImageWorkflowAction = Literal["text", "translated_image", "ask_translate"]


@dataclass(frozen=True)
class PendingImage:
    file_bytes: bytes
    caption: str | None = None


@dataclass(frozen=True)
class TranslatedImage:
    file_bytes: bytes
    file_name: str


@dataclass(frozen=True)
class ImageWorkflowResult:
    action: ImageWorkflowAction
    text: str | None = None
    translated_image: TranslatedImage | None = None
    pending_image: PendingImage | None = None


async def _classify_image_translation_intent(text: str, platform_label: str, *, user_id: int) -> str:
    if not text.strip():
        return "unknown"

    try:
        return await classify_image_translation_intent(text, user_id=user_id)
    except Exception:
        logger.exception("%s image translation intent classification failed", platform_label)
        return "unknown"


async def _translate_image(file_bytes: bytes, platform_label: str, *, user_id: int) -> ImageWorkflowResult:
    try:
        _, _, translated_image = await translate_image_bytes(
            file_bytes,
            include_res_img=True,
            user_id=user_id,
        )
    except TranslateInputError as exc:
        return ImageWorkflowResult(action="text", text=exc.message)
    except Exception:
        logger.exception("%s picture translation failed", platform_label)
        return ImageWorkflowResult(action="text", text=IMAGE_PROCESS_FAILED_MESSAGE)

    if translated_image is None:
        return ImageWorkflowResult(action="text", text=NO_TEXT_DETECTED_MESSAGE)

    b64_img, file_name = translated_image
    try:
        translated_file_bytes = base64.b64decode(b64_img)
    except Exception:
        logger.exception("%s translated image decode failed", platform_label)
        return ImageWorkflowResult(action="text", text=IMAGE_PROCESS_FAILED_MESSAGE)

    return ImageWorkflowResult(
        action="translated_image",
        translated_image=TranslatedImage(
            file_bytes=translated_file_bytes,
            file_name=file_name,
        ),
    )


async def _answer_image(
    platform: str,
    platform_user_id: str,
    file_bytes: bytes,
    *,
    caption: str | None,
    username: str | None,
    display_name: str | None,
    language_code: str | None,
    platform_label: str,
    user_id: int,
) -> ImageWorkflowResult:
    try:
        result = await route_image_message(
            platform,
            platform_user_id,
            file_bytes,
            prompt=caption,
            username=username,
            display_name=display_name,
            language_code=language_code,
            user_id=user_id,
        )
    except Exception:
        logger.exception("%s picture understanding failed", platform_label)
        return ImageWorkflowResult(action="text", text=IMAGE_UNDERSTANDING_FAILED_MESSAGE)

    return ImageWorkflowResult(action="text", text=result)


async def handle_incoming_image(
    platform: str,
    platform_user_id: str,
    file_bytes: bytes,
    *,
    caption: str | None = None,
    force_translate: bool = False,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
    platform_label: str | None = None,
) -> ImageWorkflowResult:
    caption = (caption or "").strip()
    label = platform_label or platform
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    user_id = user.id

    should_translate = force_translate
    if not should_translate and caption:
        should_translate = (
            await _classify_image_translation_intent(caption, label, user_id=user_id)
        ) == "translate"

    if should_translate:
        return await _translate_image(file_bytes, label, user_id=user_id)

    try:
        is_manga = await asyncio.to_thread(is_manga_image_bytes, file_bytes)
    except TranslateInputError as exc:
        return ImageWorkflowResult(action="text", text=exc.message)
    except Exception:
        logger.exception("%s comic detection failed; falling back to image answer", label)
        return await _answer_image(
            platform,
            platform_user_id,
            file_bytes,
            caption=caption,
            username=username,
            display_name=display_name,
            language_code=language_code,
            platform_label=label,
            user_id=user_id,
        )

    if is_manga:
        return ImageWorkflowResult(
            action="ask_translate",
            text=ASK_TRANSLATE_MESSAGE,
            pending_image=PendingImage(file_bytes=file_bytes, caption=caption),
        )

    return await _answer_image(
        platform,
        platform_user_id,
        file_bytes,
        caption=caption,
        username=username,
        display_name=display_name,
        language_code=language_code,
        platform_label=label,
        user_id=user_id,
    )


async def handle_pending_image_reply(
    platform: str,
    platform_user_id: str,
    pending_image: PendingImage,
    text: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
    platform_label: str | None = None,
) -> ImageWorkflowResult:
    label = platform_label or platform
    user = upsert_user(
        platform=platform,
        platform_user_id=platform_user_id,
        username=username,
        display_name=display_name,
        language_code=language_code,
    )
    user_id = user.id
    intent = await _classify_image_translation_intent(text, label, user_id=user_id)

    if intent == "translate":
        return await _translate_image(pending_image.file_bytes, label, user_id=user_id)

    if intent == "skip":
        return await _answer_image(
            platform,
            platform_user_id,
            pending_image.file_bytes,
            caption=pending_image.caption,
            username=username,
            display_name=display_name,
            language_code=language_code,
            platform_label=label,
            user_id=user_id,
        )

    return ImageWorkflowResult(
        action="ask_translate",
        text=ASK_TRANSLATE_MESSAGE,
        pending_image=pending_image,
    )
