from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
TEMP_DIR = PROJECT_ROOT / "temp"
LOG_DIR = PROJECT_ROOT / "logs"

ENV_PATH = PROJECT_ROOT / ".env"
CONTENT_SOURCES_CONFIG_PATH = CONFIG_DIR / "content_sources.toml"
CONTENT_SOURCES_LAST_REFRESH_AT_PATH = TEMP_DIR / "content_sources_last_refresh_at"
DEFAULT_FONT_PATH = FONTS_DIR / "LXGWWenKai-Regular.ttf"
SAVED_PICTURES_DIR = TEMP_DIR / "saved_pictures"
TG_SAVED_PICTURES_DIR = SAVED_PICTURES_DIR / "tg"
QQ_SAVED_PICTURES_DIR = SAVED_PICTURES_DIR / "qq"
TRANSLATED_IMAGES_DIR = TEMP_DIR / "translated_images"
QQ_TRANSLATED_IMAGES_DIR = TRANSLATED_IMAGES_DIR / "qq"
ALL_LOG_PATH = LOG_DIR / "all.log"
APP_LOG_PATH = LOG_DIR / "app.log"
BOTPY_LOG_PATH = LOG_DIR / "botpy.log"
MODEL_DIR = ASSETS_DIR / "models"
