from fastapi import APIRouter

from app.api import auth, health, incidents, reports, rules, targets, thresholds, ws

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
router.include_router(targets.router)
router.include_router(incidents.router)
router.include_router(reports.router)
router.include_router(rules.router)
router.include_router(thresholds.router)
router.include_router(ws.router)
