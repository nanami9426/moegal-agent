import os
from threading import Lock

import torch
from manga_ocr import MangaOcr
from ultralytics import YOLO
from utils.logger import logger
from config.paths import MODEL_DIR

DET_MODEL_PATH = MODEL_DIR / "comic-text-segmenter.pt"
MOCR_MODEL_PATH = MODEL_DIR / "manga-ocr-base"

MODEL_LOCK = Lock()
DET_MODEL: YOLO | None = None
MOCR: MangaOcr | None = None
USE_GPU = os.getenv("USE_GPU")

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

def warmup_models() -> tuple[YOLO, MangaOcr]:
    global DET_MODEL, MOCR

    with MODEL_LOCK:
        if DET_MODEL is not None and MOCR is not None:
            return DET_MODEL, MOCR

        use_cuda = (USE_GPU is not None
                    and USE_GPU.strip().lower() == "true"
                    and is_cuda_runtime_usable())
        
        device = torch.device("cuda:0") if use_cuda else torch.device("cpu")

        if DET_MODEL is None:
            DET_MODEL = YOLO(str(DET_MODEL_PATH)).to(device)
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


def get_det_model() -> YOLO:
    if DET_MODEL is not None:
        return DET_MODEL
    det_model, _ = warmup_models()
    return det_model


def get_mocr() -> MangaOcr:
    if MOCR is not None:
        return MOCR
    _, mocr = warmup_models()
    return mocr
