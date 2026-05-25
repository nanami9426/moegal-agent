from functools import lru_cache

from PIL import ImageFont

from config.paths import DEFAULT_FONT_PATH

FONT_PATH = str(DEFAULT_FONT_PATH)


@lru_cache(maxsize=2048)
def load_font(font_path: str, font_size: int):
    return ImageFont.truetype(font_path, font_size)


def glyph_area(font) -> int:
    bbox = font.getbbox("中")
    h = max(1, bbox[3] - bbox[1])
    w = max(1, bbox[2] - bbox[0])
    return h * w


@lru_cache(maxsize=4096)
def calc_font_size(font_path: str, max_height: int, max_width: int, text_len: int) -> int:
    if text_len <= 0 or max_height <= 0 or max_width <= 0:
        return 10
    target_area = max_height * max_width * 0.55
    high = max(10, min(512, max(max_height, max_width) * 2))
    low = 1
    best = 1
    while low <= high:
        mid = (low + high) // 2
        area = glyph_area(load_font(font_path, mid)) * text_len
        if area <= target_area:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


class FontConfig:
    def __init__(self, max_height, max_width, text, font_path=FONT_PATH):
        self.font_path = str(font_path)
        self.font_size = calc_font_size(self.font_path, int(max_height), int(max_width), len(text))

    @property
    def font(self):
        return load_font(self.font_path, self.font_size)
