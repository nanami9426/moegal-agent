import asyncio
import logging
import os
from logging.handlers import TimedRotatingFileHandler

import botpy
from botpy.message import C2CMessage

from config.paths import BOTPY_LOG_PATH, LOG_DIR
from utils.logger import logger
from agent.router import route_message


class QQClient(botpy.Client):
    async def on_ready(self):
        logger.info("QQ 机器人【%s】已启动", self.robot.name)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("QQ bot event error: %s", event_method)

    async def on_c2c_message_create(self, message: C2CMessage):
        content = (message.content or "").strip()
        logger.info(
            "收到 QQ C2C 消息 openid=%s msg_id=%s content=%r",
            message.author.user_openid,
            message.id,
            content,
        )
        result_str = await route_message("qq", message.author.user_openid, content)
        await message.reply(msg_type=0, content=result_str)

def build_client() -> QQClient:
    intents = botpy.Intents(public_messages=True)
    LOG_DIR.mkdir(exist_ok=True)
    return QQClient(
        intents=intents,
        timeout=15,
        ext_handlers={
            "handler": TimedRotatingFileHandler,
            "format": "%(asctime)s\t[%(levelname)s]\t(%(filename)s:%(lineno)s)%(funcName)s\t%(message)s",
            "level": logging.DEBUG,
            "when": "D",
            "backupCount": 7,
            "encoding": "utf-8",
            "filename": str(BOTPY_LOG_PATH),
        },
    )


def run_client() -> None:
    appid = os.getenv("QQ_BOT_APPID")
    secret = os.getenv("QQ_BOT_SK")
    if not appid or not secret:
        raise RuntimeError(
            "缺少 QQ_BOT_APPID 或 QQ_BOT_SK. 请先在 .env 里配置。"
        )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        client = build_client()
        client.run(appid=appid, secret=secret)
    except Exception:
        logger.exception("QQ bot stopped unexpectedly.")
    finally:
        asyncio.set_event_loop(None)
        loop.close()
