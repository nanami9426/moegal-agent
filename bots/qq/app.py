import asyncio
import logging
import os
import posixpath
import uuid
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from urllib.parse import quote, urlparse
import paramiko
import botpy
import httpx
from botpy.message import C2CMessage

from config.paths import BOTPY_LOG_PATH, LOG_DIR, QQ_SAVED_PICTURES_DIR, QQ_TRANSLATED_IMAGES_DIR
from utils.logger import logger
from agent.router import route_message, start_new_conversation_context
from agent.graph import close_chat_graphs
from services.account.bindings import complete_platform_link
from services.image_workflow import (
    ImageWorkflowResult,
    PendingImage,
    TranslatedImage,
    handle_incoming_image,
    handle_pending_image_reply,
)
from services.account.memory_consolidation import close_memory_consolidation_tasks


PENDING_TRANSLATE_COMMAND = "/translate"
NEWCHAT_COMMAND = "/newchat"
LINK_COMMAND = "/link"
QQ_IMAGE_DOWNLOAD_FAILED_MESSAGE = "图片下载失败，请稍后再试。"
QQ_PUBLIC_IMAGE_FAILED_MESSAGE = "翻译后的图片已生成，但发送失败，请检查公开图片地址配置。"
TRANSLATE_PROMPT_MESSAGE = "请发送要翻译的图片。"
NEWCHAT_MESSAGE = "已开启新的对话上下文。订阅和摘要记录不会受影响。"
ALREADY_NEWCHAT_MESSAGE = "已在新对话中。"
LINK_USAGE_MESSAGE = "用法：/link 绑定码"


class QQClient(botpy.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_comic_images: dict[str, PendingImage] = {}
        self._pending_translate_users: set[str] = set()

    def _ensure_image_state(self) -> None:
        if not hasattr(self, "_pending_comic_images"):
            self._pending_comic_images = {}
        if not hasattr(self, "_pending_translate_users"):
            self._pending_translate_users = set()

    async def on_ready(self):
        logger.info("QQ 机器人【%s】已启动", self.robot.name)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("QQ bot event error: %s", event_method)

    async def on_c2c_message_create(self, message: C2CMessage):
        self._ensure_image_state()
        content = (message.content or "").strip()
        openid = message.author.user_openid
        image_attachment = _first_image_attachment(message)
        logger.info(
            "收到 QQ C2C 消息 openid=%s msg_id=%s content=%r has_image=%s",
            openid,
            message.id,
            content,
            image_attachment is not None,
        )

        if image_attachment is not None:
            await self._handle_image_message(message, openid, content, image_attachment)
            return

        if content == PENDING_TRANSLATE_COMMAND:
            self._pending_comic_images.pop(openid, None)
            self._pending_translate_users.add(openid)
            await message.reply(msg_type=0, content=TRANSLATE_PROMPT_MESSAGE)
            return

        if content == NEWCHAT_COMMAND:
            result = start_new_conversation_context("qq", openid)
            reply = NEWCHAT_MESSAGE if result.created else ALREADY_NEWCHAT_MESSAGE
            await message.reply(msg_type=0, content=reply)
            return

        link_code = _parse_command_arg(content, LINK_COMMAND)
        if link_code is not None:
            await self._handle_link_command(message, openid, link_code)
            return

        pending_image = self._pending_comic_images.get(openid)
        if pending_image is not None:
            result = await handle_pending_image_reply(
                "qq",
                openid,
                pending_image,
                content,
                platform_label="QQ",
            )
            if result.action == "ask_translate":
                self._pending_comic_images[openid] = result.pending_image or pending_image
            else:
                self._pending_comic_images.pop(openid, None)
            await self._reply_with_image_workflow_result(message, openid, result)
            return

        result_str = await route_message("qq", openid, content)
        await message.reply(msg_type=0, content=result_str)

    async def _handle_link_command(
        self,
        message: C2CMessage,
        openid: str,
        code: str,
    ) -> None:
        if not code:
            await message.reply(msg_type=0, content=LINK_USAGE_MESSAGE)
            return

        try:
            result = complete_platform_link(
                platform="qq",
                platform_user_id=openid,
                code=code,
            )
        except ValueError as exc:
            await message.reply(msg_type=0, content=str(exc))
            return

        if result.already_bound:
            reply = "该 QQ 账号已经绑定到此 Web 用户。"
        else:
            reply = "绑定成功。现在可以在 Web 管理后台查看该 QQ 账号的数据。"
        await message.reply(msg_type=0, content=reply)

    async def _handle_image_message(self, message: C2CMessage, openid: str, content: str, attachment) -> None:
        try:
            file_bytes = await _download_image_attachment(message, openid, attachment)
        except Exception:
            logger.exception("QQ picture download failed")
            await message.reply(msg_type=0, content=QQ_IMAGE_DOWNLOAD_FAILED_MESSAGE)
            return

        force_translate = openid in self._pending_translate_users
        self._pending_translate_users.discard(openid)
        if force_translate:
            self._pending_comic_images.pop(openid, None)

        result = await handle_incoming_image(
            "qq",
            openid,
            file_bytes,
            caption=content,
            force_translate=force_translate,
            platform_label="QQ",
        )

        if result.action == "ask_translate":
            self._pending_comic_images[openid] = result.pending_image or PendingImage(
                file_bytes=file_bytes,
                caption=content,
            )
        else:
            self._pending_comic_images.pop(openid, None)

        await self._reply_with_image_workflow_result(message, openid, result)

    async def _reply_with_image_workflow_result(
        self,
        message: C2CMessage,
        openid: str,
        result: ImageWorkflowResult,
    ) -> None:
        if result.action == "translated_image" and result.translated_image is not None:
            await self._send_translated_image(message, openid, result.translated_image)
            return

        await message.reply(msg_type=0, content=result.text or "我现在没有生成可发送的回复。")

    async def _send_translated_image(
        self,
        message: C2CMessage,
        openid: str,
        translated_image: TranslatedImage,
    ) -> None:
        image_url = await asyncio.to_thread(_save_public_translated_image, translated_image)
        if image_url is None:
            logger.error("QQ translated image public URL is unavailable")
            await message.reply(msg_type=0, content=QQ_PUBLIC_IMAGE_FAILED_MESSAGE)
            return

        try:
            media = await self.api.post_c2c_file(
                openid,
                file_type=1,
                url=image_url,
                srv_send_msg=False,
            )
            await message.reply(msg_type=7, media=media)
        except Exception:
            logger.exception("QQ translated image media send failed")
            await message.reply(msg_type=0, content=QQ_PUBLIC_IMAGE_FAILED_MESSAGE)


def _first_image_attachment(message: C2CMessage):
    for attachment in getattr(message, "attachments", []) or []:
        url = getattr(attachment, "url", None)
        if not url:
            continue

        content_type = (getattr(attachment, "content_type", None) or "").lower()
        filename = (getattr(attachment, "filename", None) or "").lower()
        if content_type.startswith("image/") or filename.endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ):
            return attachment

    return None


def _parse_command_arg(content: str, command: str) -> str | None:
    if content == command:
        return ""
    if content.startswith(f"{command} "):
        return content[len(command):].strip()
    return None


async def _download_image_attachment(message: C2CMessage, openid: str, attachment) -> bytes:
    url = attachment.url
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    file_bytes = response.content
    folder_path = QQ_SAVED_PICTURES_DIR / openid
    folder_path.mkdir(parents=True, exist_ok=True)
    file_name = _safe_filename(
        getattr(attachment, "filename", None)
        or Path(urlparse(url).path).name
        or f"{getattr(message, 'id', 'message')}.jpg"
    )
    message_id = _safe_filename(str(getattr(message, "id", "message")))
    file_save_path = folder_path / f"{message_id}_{file_name}"
    file_save_path.write_bytes(file_bytes)
    return file_bytes


def _save_public_translated_image(translated_image: TranslatedImage) -> str | None:
    file_name = _unique_public_filename(translated_image.file_name)
    QQ_TRANSLATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (QQ_TRANSLATED_IMAGES_DIR / file_name).write_bytes(translated_image.file_bytes)

    base_url = (os.getenv("MOEGAL_PUBLIC_ASSET_BASE_URL") or "").strip().rstrip("/")
    if not base_url or not _remote_image_upload_configured():
        return None

    try:
        _upload_translated_image_to_remote(file_name, translated_image.file_bytes)
    except Exception:
        logger.exception("QQ translated image remote upload failed")
        return None

    return f"{base_url}/image/{quote(file_name)}"


def _remote_image_upload_configured() -> bool:
    return bool(
        (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_HOST") or "").strip()
        or (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_DIR") or "").strip()
    )


def _upload_translated_image_to_remote(file_name: str, file_bytes: bytes) -> None:
    host = (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_HOST") or "").strip()
    remote_dir = (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_DIR") or "").strip().rstrip("/")
    if not host or not remote_dir:
        raise RuntimeError("MOEGAL_QQ_IMAGE_REMOTE_HOST and MOEGAL_QQ_IMAGE_REMOTE_DIR are required")

    user = (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_USER") or "").strip()
    if not user:
        raise RuntimeError("MOEGAL_QQ_IMAGE_REMOTE_USER is required")
    password = os.getenv("MOEGAL_QQ_IMAGE_REMOTE_PASSWORD")
    key_filename = (os.getenv("MOEGAL_QQ_IMAGE_REMOTE_KEY_FILE") or "").strip() or None
    port = int((os.getenv("MOEGAL_QQ_IMAGE_REMOTE_PORT") or "22").strip())
    timeout = float((os.getenv("MOEGAL_QQ_IMAGE_REMOTE_TIMEOUT_SECONDS") or "15").strip())
    remote_path = posixpath.join(remote_dir, file_name)

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=host,
            port=port,
            username=user,
            password=password,
            key_filename=key_filename,
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
        )
        with ssh.open_sftp() as sftp:
            _ensure_remote_dir(sftp, remote_dir)
            with sftp.file(remote_path, "wb") as remote_file:
                remote_file.write(file_bytes)
    finally:
        ssh.close()


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    remote_dir = remote_dir.rstrip("/")
    paths: list[str] = []
    while remote_dir and remote_dir != "/":
        paths.append(remote_dir)
        remote_dir = posixpath.dirname(remote_dir)

    for path in reversed(paths):
        try:
            sftp.stat(path)
        except OSError:
            sftp.mkdir(path)


def _safe_filename(file_name: str | None) -> str:
    safe_name = Path(file_name or "image.png").name
    return safe_name or "image.png"


def _unique_public_filename(file_name: str | None) -> str:
    safe_name = _safe_filename(file_name)
    suffix = Path(safe_name).suffix or ".png"
    stem = Path(safe_name).stem or "image"
    return f"{stem}_{uuid.uuid4().hex}{suffix}"


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
        if not loop.is_closed():
            loop.run_until_complete(close_memory_consolidation_tasks())
            loop.run_until_complete(close_chat_graphs())
        asyncio.set_event_loop(None)
        loop.close()
