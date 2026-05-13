import logging
import re
from pathlib import Path
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class TelegramGetUpdatesFilter(logging.Filter):
    """
    过滤 Telegram bot getUpdates 的 httpx 请求日志。
    只影响命令行和 app.log，不影响 all.log。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()

        is_telegram_get_updates = (
            "HTTP Request:" in msg
            and "api.telegram.org/bot" in msg
            and "/getUpdates" in msg
        )

        return not is_telegram_get_updates


class RedactTelegramTokenFilter(logging.Filter):
    """
    避免 Telegram Bot Token 被写进日志。
    """

    TOKEN_PATTERN = re.compile(r"(https://api\.telegram\.org/bot)([^/\s]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        safe_msg = self.TOKEN_PATTERN.sub(r"\1<redacted>", msg)

        if safe_msg != msg:
            record.msg = safe_msg
            record.args = ()

        return True


def setup_logging() -> logging.Logger:
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    redact_filter = RedactTelegramTokenFilter()
    telegram_noise_filter = TelegramGetUpdatesFilter()

    # 1. 所有日志
    all_file_handler = RotatingFileHandler(
        LOG_DIR / "all.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    all_file_handler.setLevel(logging.DEBUG)
    all_file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    all_file_handler.addFilter(redact_filter)

    # 2. 和命令行相同的日志
    app_file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_file_handler.setLevel(logging.INFO)
    app_file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    app_file_handler.addFilter(redact_filter)
    app_file_handler.addFilter(telegram_noise_filter)

    # 3. 命令行彩色输出
    console_handler = RichHandler(
        console=None,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
        show_time=True,
        show_level=True,
        show_path=True,
    )
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(redact_filter)
    console_handler.addFilter(telegram_noise_filter)

    root_logger.addHandler(all_file_handler)
    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)


logger = setup_logging()