from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import register_exception_handlers
from api.routes import api_router
from config import settings
from db.bootstrap import ensure_schema
from scheduler import shutdown_scheduler, start_scheduler
from services.seed_admin import seed_admin_user_if_configured


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Empty Supabase / mis-migrated DBs: create missing tables before cron jobs run.
    ensure_schema()
    seed_admin_user_if_configured()
    start_scheduler()
    yield
    shutdown_scheduler()


settings.assert_safe_for_production()

app = FastAPI(title="AI Career Copilot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.include_router(api_router)
