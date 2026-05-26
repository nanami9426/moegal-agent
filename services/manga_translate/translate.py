import asyncio
import base64
import random
import time
import cv2
import numpy as np
from PIL import Image
from services.manga_translate.ocr import get_det_model
from services.manga_translate.pic_process import TextDirection, draw_text_on_boxes, get_text_masked_pic, save_img
from utils.logger import logger

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

async def translate_req(text):
    return "test: " + text

async def translate_image_bytes(file_bytes: bytes, include_res_img: bool,
                                text_direction: TextDirection = "horizontal"):
    img_bgr_cv, img_pil = decode_image(file_bytes)
    det_model = get_det_model()
    res = det_model(img_bgr_cv, verbose=False)
    bboxes = res[0].boxes.xyxy.cpu().numpy()
    raw_text, inpaint = await get_text_masked_pic(img_pil, img_bgr_cv, bboxes, True)
    if len(raw_text) == 0:
        logger.warning("未检测出文字")
        return None, None, None, None

    translated_text = await translate_req(raw_text)
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