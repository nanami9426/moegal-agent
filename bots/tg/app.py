import os
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from bots.tg import handlers as tg_handlers

def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN. 请先在 .env 里配置 Telegram Bot Token。"
        )

    application = Application.builder().token(token).build()

    # 命令类 handler
    application.add_handler(CommandHandler("start", tg_handlers.start))
    application.add_handler(CommandHandler("help", tg_handlers.help_command))
    application.add_handler(CommandHandler("subscribe", tg_handlers.subscribe_command))
    application.add_handler(CommandHandler("digest", tg_handlers.digest_command))

    # 普通文本 handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handlers.handle_text))

    # 错误处理
    application.add_error_handler(tg_handlers.handle_error)

    return application