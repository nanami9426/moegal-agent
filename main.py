from utils.logger import logger
from bots.tg.app import build_application
from config.settings import init_settings
from db.session import init_db
from services.rsshub_container import start_rsshub_stack, stop_rsshub_stack

def main() -> None:
    init_settings()
    rsshub_runtime = start_rsshub_stack()
    init_db()
    application = build_application()
    logger.info("Moegal bot started.")
    # 本地开发先用 polling。
    # 部署到服务器后再切 webhook。
    try:
        application.run_polling()
    finally:
        stop_rsshub_stack(rsshub_runtime)


if __name__ == "__main__":
    main()
