from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.deps import register_exception_handlers
from api.routes import api_router
from scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="AI Career Copilot API", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(api_router)
