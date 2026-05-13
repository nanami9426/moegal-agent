# ========== Telegram Handlers ==========
from telegram import Update
from telegram.ext import (
    ContextTypes,
)
from pathlib import Path
from agent.router import route_message
from utils.logger import logger

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    message = (
        f"你好，{user.first_name if user else '朋友'}！\n\n"
        "我是 Moegal Agent 的早期版本。\n\n"
    )

    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "当前支持：\n\n"
        "1. 订阅关键词\n"
        "/subscribe xxx\n\n"
        "2. 查看今日摘要\n"
        "/digest"
    )

    await update.message.reply_text(message)

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /subscribe xxx
    第一版先 mock，后面写入 subscriptions 表。
    """
    target = " ".join(context.args).strip()

    if not target:
        await update.message.reply_text("用法：/subscribe 关键词\n例如：/subscribe ブルアカ")
        return

    await update.message.reply_text(
        f"已订阅：{target}\n\n"
        "之后我会在每日摘要里优先推送相关内容。"
    )


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 /digest
    第一版先 mock，后面读取数据库和订阅内容。
    """
    await update.message.reply_text(
        "今日摘要：\n\n"
        "1. 暂无真实抓取结果\n"
        "2. 当前 digest 还是 mock 数据\n"
        "3. 下一步会接入订阅表和内容抓取 worker"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理普通文本。
    """
    text = update.message.text or ""

    logger.info(
        "Received text from user_id=%s text=%s",
        update.effective_user.id if update.effective_user else None,
        text,
    )

    result = route_message(text)
    await update.message.reply_text(result)


async def handel_receive_picture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 处理图片
    message = update.message
    photo = message.photo[-1] # -1 是最大尺寸
    tg_file = await photo.get_file()
    user_id = message.from_user.id
    folder_path = Path("temp/saved_pictures/tg") / str(user_id)
    folder_path.mkdir(parents=True, exist_ok=True)
    file_save_path = folder_path / f"{user_id}_{photo.file_unique_id}.jpg"
    await tg_file.download_to_drive(file_save_path)
    await update.message.reply_text("图片已保存")
    with open(file_save_path, "rb") as f:
        await update.message.reply_photo(photo=f, caption="测试图片")

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    全局错误处理。
    """
    logger.exception("Telegram bot error: %s", context.error)
