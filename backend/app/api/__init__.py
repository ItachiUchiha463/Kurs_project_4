from fastapi import APIRouter

from app.api import auth, targets

router = APIRouter()
router.include_router(auth.router)
router.include_router(targets.router)
