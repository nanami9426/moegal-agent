# ========== Telegram Handlers ==========
import asyncio
import base64
from io import BytesIO

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from agent.router import route_message, start_new_conversation_context
from config.paths import TG_SAVED_PICTURES_DIR
from services.account.subscriptions import create_subscription, delete_subscription
from services.account.users import upsert_user
from services.manga_translate.translate import TranslateInputError, translate_image_bytes
from services.rss_pipeline.digest import mark_deliveries_sent, prepare_daily_digest
from utils.logger import logger


PENDING_TRANSLATE_PHOTO_KEY = "pending_translate_photo"


def _telegram_display_name(user) -> str | None:
    if user is None:
        return None

    parts = [user.first_name, user.last_name]
    display_name = " ".join(part for part in parts if part)
    return display_name or user.username


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    message = (
        f"你好{'，' + user.first_name if user else ''}！\n\n"
        "我是 Moegal Agent 的早期版本。\n\n"
    )

    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "当前支持：\n\n"
        "1. 订阅关键词\n"
        "/subscribe xxx\n\n"
        "2. 取消订阅关键词\n"
        "/unsubscribe xxx\n\n"
        "3. 开启新的对话上下文\n"
        "/newchat\n\n"
        "4. 查看今日摘要\n"
        "/digest\n\n"
        "5. 翻译漫画图片\n"
        "/translate"
    )

    await update.message.reply_text(message)


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /translate。
    """
    context.user_data[PENDING_TRANSLATE_PHOTO_KEY] = True
    await update.message.reply_text("请发送要翻译的漫画图片。")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /subscribe xxx。
    """
    user = update.effective_user
    target = " ".join(context.args).strip()

    if not target:
        await update.message.reply_text("用法：/subscribe 关键词")
        return

    if user is None:
        await update.message.reply_text("无法识别当前用户，请稍后再试。")
        return

    app_user = upsert_user(
        platform="tg",
        platform_user_id=str(user.id),
        username=user.username,
        display_name=_telegram_display_name(user),
        language_code=user.language_code,
    )
    result = create_subscription(user_id=app_user.id, target=target)
    subscription = result.subscription

    if result.created:
        message = f"已订阅：{subscription.target}\n\n之后我会在每日摘要里优先推送相关内容。"
    elif result.reenabled:
        message = f"已重新启用订阅：{subscription.target}"
    else:
        message = f"已订阅过：{subscription.target}\n\n我不会重复创建。"

    await update.message.reply_text(message)


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /unsubscribe xxx。
    """
    user = update.effective_user
    target = " ".join(context.args).strip()

    if not target:
        await update.message.reply_text("用法：/unsubscribe 关键词")
        return

    if user is None:
        await update.message.reply_text("无法识别当前用户，请稍后再试。")
        return

    app_user = upsert_user(
        platform="tg",
        platform_user_id=str(user.id),
        username=user.username,
        display_name=_telegram_display_name(user),
        language_code=user.language_code,
    )
    result = delete_subscription(user_id=app_user.id, target=target)

    if result.deleted and result.subscription is not None:
        message = f"已取消订阅：{result.subscription.target}"
    else:
        message = f"没有找到有效订阅：{target}"

    await update.message.reply_text(message)


async def newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /newchat。
    """
    user = update.effective_user

    if user is None:
        await update.message.reply_text("无法识别当前用户，请稍后再试。")
        return

    start_new_conversation_context("tg", str(user.id))
    await update.message.reply_text("已开启新的对话。")


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /digest。
    """
    user = update.effective_user

    if user is None:
        await update.message.reply_text("无法识别当前用户，请稍后再试。")
        return

    app_user = upsert_user(
        platform="tg",
        platform_user_id=str(user.id),
        username=user.username,
        display_name=_telegram_display_name(user),
        language_code=user.language_code,
    )
    result = await asyncio.to_thread(prepare_daily_digest, app_user.id)

    await update.message.reply_text(result.text)

    if result.delivery_ids:
        # 如果这次 digest 有内容，就把对应的 delivery 标记为 sent
        # 防止重复推送，用户下一次 /digest 就不会发送已经发过的内容
        await asyncio.to_thread(mark_deliveries_sent, result.delivery_ids)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理普通文本。
    """
    user = update.effective_user
    text = update.message.text or ""

    logger.info(
        "Received text from user_id=%s text=%s",
        update.effective_user.id if update.effective_user else None,
        text,
    )

    if user is None:
        await update.message.reply_text("无法识别当前用户，请稍后再试。")
        return

    result = await route_message(
        "tg",
        str(user.id),
        text,
        username=user.username,
        display_name=_telegram_display_name(user),
        language_code=user.language_code,
    )
    await update.message.reply_text(result)


async def handel_receive_picture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 处理图片
    message = update.message
    if not context.user_data.get(PENDING_TRANSLATE_PHOTO_KEY):
        await message.reply_text("请先发送 /translate，然后再发送漫画图片。")
        return

    context.user_data.pop(PENDING_TRANSLATE_PHOTO_KEY, None)

    photo = message.photo[-1] # -1 是最大尺寸
    tg_file = await photo.get_file()
    user_id = message.from_user.id
    folder_path = TG_SAVED_PICTURES_DIR / str(user_id)
    folder_path.mkdir(parents=True, exist_ok=True)
    file_save_path = folder_path / f"{user_id}_{photo.file_unique_id}.jpg"
    await tg_file.download_to_drive(file_save_path)
    await update.message.reply_text("图片已保存")

    try:
        file_bytes = bytes(await tg_file.download_as_bytearray())
        _, _, translated_image = await translate_image_bytes(file_bytes, include_res_img=True)
    except TranslateInputError as exc:
        await update.message.reply_text(exc.message)
        return
    except Exception:
        logger.exception("Telegram picture translation failed")
        await update.message.reply_text("图片处理失败，请稍后再试。")
        return

    if translated_image is None:
        await update.message.reply_text("未检测出文字")
        return

    b64_img, file_name = translated_image
    translated_photo = BytesIO(base64.b64decode(b64_img))
    translated_photo.name = file_name
    await update.message.reply_photo(photo=translated_photo, caption="翻译后的图片")
    # 把读指针移到开头
    translated_photo.seek(0)
    await update.message.reply_document(document=translated_photo, caption="翻译后的图片")

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    全局错误处理。
    """
    logger.exception("Telegram bot error: %s", context.error)
