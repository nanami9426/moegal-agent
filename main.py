import threading

from utils.logger import logger
from bots.tg.app import build_application
from bots.qq.app import run_client as run_qq_client
from config.settings import init_settings
from db.session import init_db
from services.manga_translate.ocr import init_ocr_models
from services.rss_pipeline.refresher import start_rss_cache_refresher
from services.runtime.rsshub import start_rsshub_stack, stop_rsshub_stack


def main() -> None:
    init_settings()
    rsshub_runtime = start_rsshub_stack()
    rss_refresher = None
    try:
        init_db()
        init_ocr_models()
        rss_refresher = start_rss_cache_refresher()
        application = build_application()
        threading.Thread(
            target=run_qq_client,
            name="qq-bot",
            daemon=True,
        ).start()
        # 本地开发先用 polling。
        # 部署到服务器后再切 webhook。
        application.run_polling()
    finally:
        if rss_refresher is not None:
            rss_refresher.stop()
        stop_rsshub_stack(rsshub_runtime)


if __name__ == "__main__":
    main()
