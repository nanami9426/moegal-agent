from fastapi import APIRouter

from web.api.admin import router as admin_router
from web.api.auth import router as auth_router
from web.api.chat import router as chat_router
from web.api.usage import router as usage_router


router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(usage_router)
router.include_router(chat_router)
