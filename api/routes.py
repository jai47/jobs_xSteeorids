"""Aggregate API routers."""

from fastapi import APIRouter

from api.routers.applications import router as applications_router
from api.routers.auth import router as auth_router
from api.routers.autopilot import router as autopilot_router
from api.routers.cover_letters import router as cover_letters_router
from api.routers.digest import router as digest_router
from api.routers.health import router as health_router
from api.routers.linkedin_insights import router as linkedin_insights_router
from api.routers.networks import router as networks_router
from api.routers.notifications import router as notifications_router
from api.routers.opportunities import router as opportunities_router
from api.routers.pipeline import router as pipeline_router
from api.routers.reports import router as reports_router
from api.routers.stories import router as stories_router
from api.routers.resumes import router as resumes_router
from api.routers.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(digest_router)
api_router.include_router(opportunities_router)
api_router.include_router(notifications_router)
api_router.include_router(applications_router)
api_router.include_router(cover_letters_router)
api_router.include_router(networks_router)
api_router.include_router(linkedin_insights_router)
api_router.include_router(autopilot_router)
api_router.include_router(stories_router)
api_router.include_router(resumes_router)
api_router.include_router(pipeline_router)
api_router.include_router(reports_router)
