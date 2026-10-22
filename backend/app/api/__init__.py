from fastapi import APIRouter

from app.api import auth, incidents, targets

router = APIRouter()
router.include_router(auth.router)
router.include_router(targets.router)
router.include_router(incidents.router)
