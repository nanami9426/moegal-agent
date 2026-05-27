import os
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from bots.tg import handlers as tg_handlers

def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    proxy_url = os.getenv("TG_PROXY_URL")

    if not token:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN. 请先在 .env 里配置 Telegram Bot Token。"
        )

    builder = Application.builder().token(token)
    if proxy_url:
        builder = builder.request(HTTPXRequest(proxy=proxy_url)).get_updates_request(
            HTTPXRequest(proxy=proxy_url)
        )

    application = builder.build()

    # 命令类 handler
    application.add_handler(CommandHandler("start", tg_handlers.start))
    application.add_handler(CommandHandler("help", tg_handlers.help_command))
    application.add_handler(CommandHandler("subscribe", tg_handlers.subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", tg_handlers.unsubscribe_command))
    application.add_handler(CommandHandler("newchat", tg_handlers.newchat_command))
    application.add_handler(CommandHandler("digest", tg_handlers.digest_command))
    application.add_handler(CommandHandler("translate", tg_handlers.translate_command))

    # 普通文本 handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handlers.handle_text))
    
    # 图片 handler
    application.add_handler(MessageHandler(filters.PHOTO, tg_handlers.handel_receive_picture))

    # 错误处理
    application.add_error_handler(tg_handlers.handle_error)

    return application
