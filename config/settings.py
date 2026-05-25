from dotenv import load_dotenv

from config.paths import ENV_PATH


def init_settings():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
