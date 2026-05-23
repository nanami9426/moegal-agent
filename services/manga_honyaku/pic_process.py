import asyncio
import os
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from services.manga_honyaku.ocr import get_mocr

OCR_MAX_CONCURRENCY = max(1, int(os.getenv("OCR_MAX_CONCURRENCY", "2")))
INPAINT_RADIUS = 2
TextDirection = Literal["horizontal", "vertical"]
MIN_FONT_SIZE = 1

def sanitize_bbox(bbox, width: int, height: int):
    x1, y1, x2, y2 = map(int, bbox)
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))
    return x1, y1, x2, y2

def build_text_mask(cropped_cv: np.ndarray) -> np.ndarray:
    # 提取疑似文字区域的二值 mask
    if cropped_cv.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    
    # 彩色转灰度（文字检测依赖亮度差异，不需要颜色信息）
    gray = cv2.cvtColor(cropped_cv, cv2.COLOR_BGR2GRAY)
    # 用高斯模糊减少噪点，避免小颗粒被判断成文字
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # 黑帽突出深色细节，可避免把半透明气泡整体选进掩码。
    # 黑帽 = 闭运算后的图像减去原图，闭运算即先膨胀再腐蚀。
    # 结果就是深色文字区域变亮，背景就接近0
    kernel_size = max(3, min(11, (min(cropped_cv.shape[:2]) // 10) * 2 + 1)) # Shape([h, w, c])
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    blackhat = cv2.morphologyEx(blur, cv2.MORPH_BLACKHAT, kernel)
    _, bh_mask = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU) # 自动计算阈值

    # 兜底保留极深像素，兼容描边文字。
    p15 = float(np.percentile(blur, 15))
    dark_threshold = int(max(30, min(120, p15)))
    dark_mask = cv2.inRange(blur, 0, dark_threshold)

    merged = cv2.bitwise_or(bh_mask, dark_mask) # 把黑帽检测出来的细节区域和深色像素区域合并。

    # merged -> 0 不是文字，255 可能是文字，也可能是噪点
    # 因此要筛选文字区域
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    filtered = np.zeros_like(merged)
    area = cropped_cv.shape[0] * cropped_cv.shape[1]
    min_area = max(6, int(area * 0.0002))
    max_area = max(20, int(area * 0.2))
    for idx in range(1, num_labels):
        component_area = int(stats[idx, cv2.CC_STAT_AREA])
        if min_area <= component_area <= max_area:
            filtered[labels == idx] = 255

    return cv2.dilate(filtered, np.ones((2, 2), dtype=np.uint8), iterations=1) # 膨胀一次再返回

async def get_text_masked_pic(image_pil, image_cv, bboxes, inpaint=True):
    # 对图片中给定的多个框 bboxes 进行 OCR 识别，同时生成文字区域 mask，并可用 inpaint 把文字从原图中抹掉。
    mask = np.zeros(image_cv.shape[:2], dtype=np.uint8)
    if len(bboxes) == 0:
        return [], image_cv

    height, width = image_cv.shape[:2]
    mocr = get_mocr()
    semaphore = asyncio.Semaphore(min(OCR_MAX_CONCURRENCY, len(bboxes)))

    async def ocr_and_mask(bbox):
        x1, y1, x2, y2 = sanitize_bbox(bbox, width, height)
        cropped_image = image_pil.crop((x1, y1, x2, y2))
        async with semaphore:
            text = await asyncio.to_thread(mocr, cropped_image)
        local_mask = build_text_mask(image_cv[y1:y2, x1:x2])
        return text, (x1, y1, x2, y2), local_mask

    tasks = [ocr_and_mask(bbox) for bbox in bboxes]
    results = await asyncio.gather(*tasks)
    all_text = []
    for text, (x1, y1, x2, y2), local_mask in results:
        all_text.append(text)
        if local_mask.size == 0:
            continue
        # 把局部 mask 合并到全图 mask 上
        target = mask[y1:y2, x1:x2]
        # out=target，即把结果写入 target
        # target 是局部 view，改动会同步到全图mask 
        np.maximum(target, local_mask, out=target)

    if inpaint and np.any(mask):
        # 抹掉文字
        image_cv = cv2.inpaint(image_cv, mask, inpaintRadius=INPAINT_RADIUS, flags=cv2.INPAINT_TELEA)
    return all_text, image_cv