from utils.logger import logger
from bots.tg.app import build_application
from config.settings import init_settings

def main() -> None:
    init_settings()
    application = build_application()

    logger.info("ACG Agent Hub bot started.")

    # 本地开发先用 polling。
    # 部署到服务器后再切 webhook。
    application.run_polling()


if __name__ == "__main__":
    main()