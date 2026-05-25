import asyncio
import os
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config.font_conf import FontConfig
from config.paths import SAVED_DIR
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

def wrap_text_by_width(draw: ImageDraw.ImageDraw, text, font, max_width):
    """
    将文字根据实际像素宽度换行，返回行列表
    """
    lines = []
    line = ''
    for char in text:
        test_line = line + char
        w = draw.textlength(test_line, font=font)
        if w <= max_width:
            line = test_line
        else:
            if line:
                lines.append(line)
            line = char
    if line:
        lines.append(line)
    return lines

def pick_text_style(cropped_cv: np.ndarray):
    if cropped_cv.size == 0:
        return (20, 20, 20), (245, 245, 245)
    gray = cv2.cvtColor(cropped_cv, cv2.COLOR_BGR2GRAY)
    median_luma = float(np.median(gray))
    if median_luma >= 145:
        return (20, 20, 20), (245, 245, 245)
    return (245, 245, 245), (20, 20, 20)

def draw_horizontal_text(draw: ImageDraw.ImageDraw, image: np.ndarray, box: tuple[int, int, int, int], text: str):
    x1, y1, x2, y2 = box
    box_width = x2 - x1
    box_height = y2 - y1
    font = FontConfig(box_height, box_width, text).font
    lines = wrap_text_by_width(draw, text, font, box_width)
    line_spacing = 4
    line_height = font.getbbox("中")[3] - font.getbbox("中")[1]
    total_height = line_height * len(lines) + line_spacing * max(0, len(lines) - 1)
    # 如果文字总高度小于框高度，就把剩余空间平均分到上下两边，实现垂直居中。
    start_y = y1 + max(0, (box_height - total_height) // 2)
    fill_color, stroke_color = pick_text_style(image[y1:y2, x1:x2])
    stroke_width = max(1, int(font.size * 0.12)) # 描边宽度
    for i, line in enumerate(lines):
        y = start_y + i * (line_height + line_spacing)
        line_width = draw.textlength(line, font=font)
        x = x1 + max(0, int((box_width - line_width) / 2)) # 水平居中
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        
def vertical_layout(text: str, font, box_height: int):
    gap = max(2, int(font.size * 0.1))
    bbox = font.getbbox("中")
    char_width = max(1, bbox[2] - bbox[0])
    char_height = max(1, bbox[3] - bbox[1])
    rows_per_col = max(1, (box_height + gap) // (char_height + gap))
    columns = [text[i:i + rows_per_col] for i in range(0, len(text), rows_per_col)]
    max_rows = max((len(column) for column in columns), default=0)
    total_width = len(columns) * char_width + gap * max(0, len(columns) - 1)
    total_height = max_rows * char_height + gap * max(0, max_rows - 1)
    return {
        "gap": gap,
        "char_width": char_width,
        "char_height": char_height,
        "rows_per_col": rows_per_col,
        "columns": columns,
        "total_width": total_width,
        "total_height": total_height,
    }


def fit_vertical_font(box_height: int, box_width: int, text: str):
    font_config = FontConfig(box_height, box_width, text)
    font_size = max(MIN_FONT_SIZE, int(font_config.font_size))
    while font_size >= MIN_FONT_SIZE:
        font = ImageFont.truetype(font_config.font_path, font_size)
        layout = vertical_layout(text, font, box_height)
        if layout["total_width"] <= box_width and layout["total_height"] <= box_height:
            return font, layout
        font_size -= 1
    font = ImageFont.truetype(font_config.font_path, MIN_FONT_SIZE)
    return font, vertical_layout(text, font, box_height)


def draw_vertical_text(draw: ImageDraw.ImageDraw, image: np.ndarray, box: tuple[int, int, int, int], text: str):
    x1, y1, x2, y2 = box
    box_width = x2 - x1
    box_height = y2 - y1
    font, layout = fit_vertical_font(box_height, box_width, text)
    gap = layout["gap"]
    columns = layout["columns"]
    char_width = layout["char_width"]
    char_height = layout["char_height"]
    total_width = layout["total_width"]
    total_height = layout["total_height"]
    start_x = x1 + max(0, (box_width - total_width) // 2)
    start_y = y1 + max(0, (box_height - total_height) // 2)
    fill_color, stroke_color = pick_text_style(image[y1:y2, x1:x2])
    stroke_width = max(1, int(font.size * 0.12))

    for col_idx, column in enumerate(columns):
        x = start_x + (len(columns) - col_idx - 1) * (char_width + gap)
        for row_idx, char in enumerate(column):
            y = start_y + row_idx * (char_height + gap)
            char_bbox = font.getbbox(char)
            actual_width = max(1, char_bbox[2] - char_bbox[0])
            actual_height = max(1, char_bbox[3] - char_bbox[1])
            draw_x = x + max(0, (char_width - actual_width) // 2)
            draw_y = y + max(0, (char_height - actual_height) // 2)
            draw.text(
                (draw_x, draw_y),
                char,
                font=font,
                fill=fill_color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )


def draw_text_on_boxes(image: np.ndarray, boxes: list, texts: list, text_direction: TextDirection = "horizontal") -> np.ndarray:
    height, width = image.shape[:2]
    img_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    for box, text in zip(boxes, texts):
        x1, y1, x2, y2 = sanitize_bbox(box, width, height)
        if not text:
            continue
        sanitized_box = (x1, y1, x2, y2)
        if text_direction == "vertical":
            draw_vertical_text(draw, image, sanitized_box, text)
        elif text_direction == "horizontal":
            draw_horizontal_text(draw, image, sanitized_box, text)
        else:
            raise ValueError("text_direction 必须是 ('horizontal', 'vertical')")
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def save_img(file_bytes, pre: str, file_name: str):
    folder_path = SAVED_DIR / pre
    folder_path.mkdir(parents=True, exist_ok=True)
    with open(folder_path / file_name, "wb") as f:
        f.write(file_bytes)