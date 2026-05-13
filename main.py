from utils.logger import logger
from bots.tg.app import build_application
from config.settings import init_settings
from db.session import init_db

def main() -> None:
    init_settings()
    init_db()
    application = build_application()
    logger.info("Moegal bot started.")
    # 本地开发先用 polling。
    # 部署到服务器后再切 webhook。
    application.run_polling()


if __name__ == "__main__":
    main()
