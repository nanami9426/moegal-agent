from __future__ import annotations

import os
from threading import Lock
from typing import Any

import cv2
import numpy as np
import torch
from manga_ocr import MangaOcr
from PIL import Image
from transformers import AutoImageProcessor, RTDetrV2ForObjectDetection

from config.paths import MODEL_DIR
from utils.logger import logger

DET_MODEL_ID = "ogkalu/comic-text-and-bubble-detector"
TEXT_BUBBLE_LABEL = "text_bubble"
TEXT_BUBBLE_CONFIDENCE = 0.8
MOCR_MODEL_PATH = MODEL_DIR / "manga-ocr-base"

MODEL_LOCK = Lock()
DET_MODEL: TextBubbleDetector | None = None
MOCR: MangaOcr | None = None
USE_GPU = os.getenv("USE_GPU")


class TextBubbleDetector:
    def __init__(
        self,
        image_processor: Any,
        model: RTDetrV2ForObjectDetection,
        device: torch.device,
    ) -> None:
        self.image_processor = image_processor
        self.model = model
        self.device = device
        self.text_bubble_label_id = self._resolve_label_id()

    @classmethod
    def from_pretrained(cls, model_id: str, device: torch.device) -> "TextBubbleDetector":
        image_processor = AutoImageProcessor.from_pretrained(
            model_id,
            cache_dir=str(MODEL_DIR),
        )
        model = RTDetrV2ForObjectDetection.from_pretrained(
            model_id,
            cache_dir=str(MODEL_DIR),
        ).to(device)
        model.eval()
        return cls(image_processor=image_processor, model=model, device=device)

    def detect_text_bubbles(
        self,
        img_bgr_cv: np.ndarray,
        confidence: float = TEXT_BUBBLE_CONFIDENCE,
    ) -> np.ndarray:
        height, width = img_bgr_cv.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr_cv, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        inputs = self.image_processor(images=img_pil, return_tensors="pt")
        inputs = move_batch_to_device(inputs, self.device)
        target_sizes = torch.tensor([(height, width)], device=self.device)

        with torch.inference_mode():
            outputs = self.model(**inputs)

        results = self.image_processor.post_process_object_detection(
            outputs,
            target_sizes=target_sizes,
            threshold=confidence,
        )[0]
        boxes = results["boxes"].detach().cpu()
        scores = results["scores"].detach().cpu()
        labels = results["labels"].detach().cpu()
        if boxes.numel() == 0:
            return np.empty((0, 4), dtype=np.float32)

        text_bubble_mask = (labels == self.text_bubble_label_id) & (scores >= confidence)
        return boxes[text_bubble_mask].numpy().astype(np.float32, copy=False)

    def _resolve_label_id(self) -> int:
        label2id = getattr(self.model.config, "label2id", None) or {}
        if TEXT_BUBBLE_LABEL in label2id:
            return int(label2id[TEXT_BUBBLE_LABEL])

        id2label = getattr(self.model.config, "id2label", None) or {}
        for label_id, label_name in id2label.items():
            if label_name == TEXT_BUBBLE_LABEL:
                return int(label_id)

        raise RuntimeError(f"检测模型缺少 {TEXT_BUBBLE_LABEL!r} 类别")


def move_batch_to_device(batch: Any, device: torch.device) -> Any:
    if hasattr(batch, "to"):
        return batch.to(device)
    return {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in batch.items()
    }

def is_cuda_runtime_usable():
    if not torch.cuda.is_available():
        logger.warning("CUDA 不可用，torch.cuda.is_available() == False")
        return False
    try:
        a = torch.tensor([1, 2, 3], device="cuda")
        b = torch.tensor([2], device="cuda")
        _ = torch.isin(a, b)
        torch.cuda.synchronize()
        return True
    except Exception as exc:
        logger.warning(f"CUDA 不可用，{str(exc)}")
        return False
    
def is_cuda_related_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in ("cuda", "cudnn", "no kernel image", "driver", "device-side assert"))

def warmup_models() -> tuple[TextBubbleDetector, MangaOcr]:
    global DET_MODEL, MOCR

    with MODEL_LOCK:
        if DET_MODEL is not None and MOCR is not None:
            return DET_MODEL, MOCR

        use_cuda = (USE_GPU is not None
                    and USE_GPU.strip().lower() == "true"
                    and is_cuda_runtime_usable())
        
        device = torch.device("cuda:0") if use_cuda else torch.device("cpu")

        if DET_MODEL is None:
            DET_MODEL = TextBubbleDetector.from_pretrained(DET_MODEL_ID, device)
            logger.info(f"气泡检测模型加载成功，使用：{DET_MODEL.device}")

        if MOCR is None:
            if use_cuda:
                try:
                    MOCR = MangaOcr(pretrained_model_name_or_path=str(MOCR_MODEL_PATH), force_cpu=False)
                    logger.info("MangaOCR 加载成功，使用：cuda")
                except Exception as e:
                    if not is_cuda_related_error(e):
                        raise
                    logger.warning(f"MangaOCR CUDA 初始化失败，自动回退 CPU。原因：{e}")
                    MOCR = MangaOcr(pretrained_model_name_or_path=str(MOCR_MODEL_PATH), force_cpu=True)
                    logger.info("MangaOCR 加载成功，使用：cpu")
            else:
                MOCR = MangaOcr(pretrained_model_name_or_path=str(MOCR_MODEL_PATH), force_cpu=True)
                logger.info("MangaOCR 加载成功，使用：cpu")

        return DET_MODEL, MOCR


def get_det_model() -> TextBubbleDetector:
    if DET_MODEL is not None:
        return DET_MODEL
    det_model, _ = warmup_models()
    return det_model


def get_mocr() -> MangaOcr:
    if MOCR is not None:
        return MOCR
    _, mocr = warmup_models()
    return mocr


def init_ocr_models() -> None:
    logger.info("开始初始化 OCR 相关模型")
    warmup_models()
    logger.info("OCR 相关模型初始化完成")
