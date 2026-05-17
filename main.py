from utils.logger import logger
from bots.tg.app import build_application
from config.settings import init_settings
from db.session import init_db
from services.rss_pipeline.refresher import start_rss_cache_refresher
from services.runtime.rsshub import start_rsshub_stack, stop_rsshub_stack


def main() -> None:
    init_settings()
    rsshub_runtime = start_rsshub_stack()
    rss_refresher = None
    try:
        init_db()
        rss_refresher = start_rss_cache_refresher()
        application = build_application()
        logger.info("Moegal bot started.")
        # 本地开发先用 polling。
        # 部署到服务器后再切 webhook。
        application.run_polling()
    finally:
        if rss_refresher is not None:
            rss_refresher.stop()
        stop_rsshub_stack(rsshub_runtime)


if __name__ == "__main__":
    main()
