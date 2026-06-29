import asyncio
import base64
import os
import random
import time
from functools import lru_cache

import cv2
import numpy as np
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from PIL import Image

from services.manga_translate.ocr import get_det_model
from services.manga_translate.pic_process import TextDirection, draw_text_on_boxes, get_text_masked_pic, save_img
from utils.llm import get_base_url, llm_user_headers
from utils.logger import logger

TRANSLATE_SYSTEM_PROMPT = (
    "你负责漫画和日常对话翻译。将用户输入翻译成简体中文。"
    "如果输入只是标点、符号、拟声词或无法翻译的短片段，直接保留或自然转写。"
    "只输出译文，不要解释、注解、括号补充、引号或多余前后缀。"
    "保持自然对话、漫画台词或原声风格。"
)

class TranslateInputError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

def decode_image(file_bytes: bytes):
    if not file_bytes:
        raise TranslateInputError(400, "图片为空") 
    np_arr = np.frombuffer(file_bytes, np.uint8)
    img_bgr_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img_bgr_cv is None:
        raise TranslateInputError(400, "图片解码失败，请确认输入为有效图片")
    return img_bgr_cv, Image.fromarray(img_bgr_cv)

@lru_cache
def get_translate_model():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. 请先在 .env 中配置。")

    return ChatOpenAI(
        model=os.getenv("MOEGAL_MODEL"),
        api_key=api_key,
        base_url=get_base_url(),
        temperature=0.2,
    )

async def translate_sentence(sentence: str, *, user_id: int) -> str:
    response = await get_translate_model().ainvoke(
        [
            SystemMessage(content=TRANSLATE_SYSTEM_PROMPT),
            HumanMessage(content=sentence),
        ],
        extra_headers=llm_user_headers(user_id),
    )
    translated = str(response.content).strip()
    return translated or sentence

async def translate_req(text: list[str], *, user_id: int) -> list[str]:
    if len(text) == 0:
        return []

    async def translate_or_keep(sentence: str) -> str:
        if not sentence.strip():
            return sentence
        return await translate_sentence(sentence, user_id=user_id)

    return await asyncio.gather(*(translate_or_keep(sentence) for sentence in text))

def is_manga_image_bytes(file_bytes: bytes) -> bool:
    img_bgr_cv, _ = decode_image(file_bytes)
    bboxes = get_det_model().detect_text_bubbles(img_bgr_cv)
    return len(bboxes) > 0

async def translate_image_bytes(
    file_bytes: bytes,
    include_res_img: bool,
    *,
    user_id: int,
    text_direction: TextDirection = "horizontal",
):
    img_bgr_cv, img_pil = decode_image(file_bytes)
    det_model = get_det_model()
    bboxes = det_model.detect_text_bubbles(img_bgr_cv)
    raw_text, inpaint = await get_text_masked_pic(img_pil, img_bgr_cv, bboxes, True)
    if len(raw_text) == 0:
        logger.warning("未检测出文字")
        return None, None, None

    translated_text = await translate_req(raw_text, user_id=user_id)
    img_res = draw_text_on_boxes(inpaint, bboxes, translated_text, text_direction=text_direction)
    ok, buffer = cv2.imencode(".png", img_res)
    if not ok:
        raise RuntimeError("结果图片编码失败")

    cn_file_bytes = buffer.tobytes()
    file_name = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}.png"
    # asyncio.to_thread(...) 把一个同步阻塞函数丢到线程池里执行，避免它卡住当前的 async 事件循环。
    asyncio.create_task(asyncio.to_thread(save_img, cn_file_bytes, "cn", file_name))
    asyncio.create_task(asyncio.to_thread(save_img, file_bytes, "raw", file_name))
    b64_img = base64.b64encode(cn_file_bytes).decode("utf8") if include_res_img else None
    return raw_text, translated_text, (b64_img, file_name)
