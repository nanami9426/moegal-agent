from pathlib import Path

from dotenv import load_dotenv


def init_settings():
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)
