from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.deps import register_exception_handlers
from api.routes import api_router
from db.engine import get_session
from scheduler import shutdown_scheduler, start_scheduler
from services.onboarding import ensure_seed_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_session() as session:
        ensure_seed_user(session)
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="AI Career Copilot API", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(api_router)
