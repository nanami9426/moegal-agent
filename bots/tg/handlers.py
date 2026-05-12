# ========== Telegram Handlers ==========
from telegram import Update
from telegram.ext import (
    ContextTypes,
)

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


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    全局错误处理。
    """
    logger.exception("Telegram bot error: %s", context.error)
