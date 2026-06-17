"""Aggregate API routers."""

from fastapi import APIRouter

from api.routers.applications import router as applications_router
from api.routers.auth import router as auth_router
from api.routers.digest import router as digest_router
from api.routers.health import router as health_router
from api.routers.opportunities import router as opportunities_router
from api.routers.pipeline import router as pipeline_router
from api.routers.reports import router as reports_router
from api.routers.resumes import router as resumes_router
from api.routers.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(digest_router)
api_router.include_router(opportunities_router)
api_router.include_router(applications_router)
api_router.include_router(resumes_router)
api_router.include_router(pipeline_router)
api_router.include_router(reports_router)
