import argparse
import threading
from collections.abc import Sequence

from utils.logger import logger
from bots.tg.app import build_application
from bots.qq.app import run_client as run_qq_client
from config.settings import init_settings
from db.session import init_db
from services.manga_translate.ocr import init_ocr_models
from services.rss_pipeline.refresher import start_rss_cache_refresher
from services.runtime.rsshub import start_rsshub_stack, stop_rsshub_stack


DEFAULT_BOTS = ("qq", "tg")
VALID_BOTS = frozenset(DEFAULT_BOTS)


def normalize_bots(bot_values: Sequence[str] | None) -> list[str]:
    if bot_values is None:
        return list(DEFAULT_BOTS)

    bots: list[str] = []
    for raw_value in bot_values:
        value = raw_value.strip().strip("[]")
        for bot in value.split(","):
            bot_name = bot.strip()
            if not bot_name:
                continue
            if bot_name not in VALID_BOTS:
                raise ValueError(f"bot 只支持 qq 或 tg，收到: {bot_name}")
            if bot_name not in bots:
                bots.append(bot_name)

    if not bots:
        raise ValueError("bot 参数不能为空")
    return bots


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bot",
        nargs="+",
        default=None,
        metavar="{qq,tg}",
        help="要启动的机器人，默认 qq,tg。示例：--bot qq 或 --bot qq,tg",
    )
    args = parser.parse_args(argv)
    try:
        args.bot = normalize_bots(args.bot)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(bot: Sequence[str] | None = None) -> None:
    bots = normalize_bots(bot)
    logger.info("准备启动机器人: %s", ",".join(bots))

    init_settings()
    rsshub_runtime = start_rsshub_stack()
    rss_refresher = None
    try:
        init_db()
        init_ocr_models()
        rss_refresher = start_rss_cache_refresher()
        application = build_application() if "tg" in bots else None

        if "qq" in bots:
            if application is None:
                run_qq_client()
            else:
                threading.Thread(
                    target=run_qq_client,
                    name="qq-bot",
                    daemon=True,
                ).start()

        if application is not None:
            # 本地开发先用 polling。
            # 部署到服务器后再切 webhook。
            application.run_polling()
    finally:
        if rss_refresher is not None:
            rss_refresher.stop()
        stop_rsshub_stack(rsshub_runtime)


if __name__ == "__main__":
    main(bot=parse_args().bot)
